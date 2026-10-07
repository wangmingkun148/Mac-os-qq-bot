"""The reply engine: polls QQ through the native app, decides, sends and confirms."""
from __future__ import annotations
import collections
import config_check
import concurrent.futures
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from engine_delivery import DeliveryMixin
from engine_live import LiveMixin
from engine_proactive import ProactiveMixin
from engine_style import StyleMixin
from live_feed import LiveFeed
from messages import MessageArchive, Tracker, image_generation_request, addressed_to_self
from ai_client import configured as ai_configured
from llm import Model
from imaging import ImageGenerator, ImageQuota
from style import reply_profile_fields
from snapshot import parse_snapshot
from browser_agent import browser_request
from reply_shape import repeat_chain, split_reply
import random
from daily_stats import DailyStats


IMAGE_LOAD_SECONDS = 10
SLOW_REQUEST_SECONDS = 15
FAILED_RETRY_PATIENCE = 45      # seconds a failed batch may take to get back to its chat before it is dropped
LOG_LIMIT_BYTES = 2_000_000
CLEANUP_INTERVAL = 6 * 3600


class Native:
    def __init__(self):
        self.events = queue.Queue()
        self.pending = {}
        self.serial = 0
        self.write_lock = threading.Lock()
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        for line in sys.stdin:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in item and item["id"] in self.pending:
                self.pending[item["id"]].put(item.get("result", {}))
            else:
                self.events.put(item)
        self.events.put({"event": "shutdown"})

    # How long to wait for the native app's answer. Sending an image takes ~10 s of timed steps by design, so a
    # shorter limit would abandon it while it is still running (and then a second attempt would collide with it).
    TIMEOUTS = {"send_image": 40, "send": 20, "capture_image": 20, "capture_latest_image": 20, "select": 15}

    def call(self, op, **kwargs):
        with self.write_lock:
            self.serial += 1
            ident = self.serial
            q = queue.Queue()
            self.pending[ident] = q
            try:
                print(json.dumps({"id": ident, "op": op, **kwargs}, ensure_ascii=False), flush=True)
            except BrokenPipeError:
                self.pending.pop(ident, None)
                raise RuntimeError("菜单栏主程序连接已断开")
        try:
            return q.get(timeout=self.TIMEOUTS.get(op, 12))
        except queue.Empty:
            if op in ("send", "send_image"):
                return {"error": "native_timeout"}      # the keystrokes may well have gone out: never resend blindly
            raise
        finally:
            self.pending.pop(ident, None)


class Engine(StyleMixin, ProactiveMixin, LiveMixin, DeliveryMixin):
    def __init__(self, base, config, native, config_warnings=()):
        self.base, self.config, self.native = base, config, native
        self.config_warnings = list(config_warnings)
        self.status_lock = threading.RLock()
        self.live = LiveFeed(base / "runtime/live.json")
        self.live_turn = None
        self.archive = MessageArchive(base / config.get("message_archive_file", "runtime/messages.jsonl"))
        self.tracker = Tracker(self.archive)
        self.model = Model(base, config)
        self.image_generator = ImageGenerator(base, config)
        image_config = config.get("image_generation", {})
        self.image_quota = ImageQuota(
            base / image_config.get("usage_file", "runtime/image-generation-usage.json"),
            image_config.get("max_per_24h", 2),
            image_config.get("unlimited_senders", ()),
        )
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.style_model = Model(base, config)
        self.model.on_event = self.style_model.on_event = self.log
        self.style_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.style_future = None
        self.style_job = None
        self.style_retry_after = 0
        self.feedback_retry_after = 0
        self.topic_retry_after = 0
        self.next_feedback_check = 0
        self.style_state_path = base / "runtime/style-profile.json"
        try:
            self.style_state = json.loads(self.style_state_path.read_text())
        except (OSError, json.JSONDecodeError):
            self.style_state = {"groups": {}}
        self.paused = True
        self.future = None
        self.inflight = None
        self.ready_reply = None
        self.verifying = None
        self.last_reply = collections.defaultdict(float)
        self.proactive_handled_activity = {}
        self.gate_notes = {}
        self.topic_watches = []          # topics sent, waiting for their reaction window to close
        self.manual_proactive_group = None
        self.topic_preview = None        # openings written for a manual 主动发起话题, waiting for the owner's choice
        self.declined_topics = []        # [(wall time, text)] shown to the owner and not sent
        self.previews = {}
        self.sidebar_started = False
        self.initial_new = collections.Counter()
        self.changed_since = {}        # other chat -> when its sidebar preview first changed (not yet looked at)
        self.content_wait = collections.defaultdict(dict)
        self.image_load_wait = {}
        self.secondary_visit = {}
        self.prepared_images = collections.defaultdict(dict)
        self.conversations_path = base / "runtime/conversations.json"
        try:
            self.conversation_details = json.loads(self.conversations_path.read_text())
        except (OSError, json.JSONDecodeError):
            self.conversation_details = {}
        self.visible_conversations = list(config["groups"])
        self.visited = {}
        self.drafts = {}
        self.next_poll = 0
        self.retry_after = 0
        self.pending_config = None
        self.failed = None
        self.epoch = 0
        self.flight_epoch = 0
        self.failure_count = 0
        self.uncertain = None            # an uncertain send we will check before resuming on our own
        self.auto_resumes = []
        self.daily = DailyStats(base / "runtime/daily-stats.json")
        self.repeat_decided = {}         # chat -> repeated text we already rolled the dice for (once per run)
        self.sticker_ids = collections.defaultdict(set)
        self.next_cleanup = 0.0
        self.select_started = {}
        self.unavailable_until = {}
        self.last_wake = 0.0
        self.wake_interval = config.get("wake_seconds", 30)
        self.status = self._initial_status()
        for warning in self.config_warnings:
            self.log("配置提示：" + warning)
        self.live_engine()
        self.save()


    def _initial_status(self):
        c = self.config
        counters = {name: 0 for name in (
            "model_calls", "decision_calls", "proactive_calls", "proactive_sent",
            "image_moderation_calls", "image_generation_calls", "verified_images", "style_summary_calls",
            "verified_replies", "input_tokens", "output_tokens")}
        return {
            "state": "paused", "message": "已暂停；点击菜单栏图标，再点「开始」", **counters, "groups": c["groups"],
            "image_load_wait_seconds": IMAGE_LOAD_SECONDS, "secondary_chat_image_wait_seconds": 3,
            "model": c.get("ai", {}).get("model", ""),
            "message_archive": str(self.archive.path.relative_to(self.base)), "archived_messages": self.archive.count,
            "config_warnings": self.config_warnings}

    def save(self):
        with self.status_lock:
            self.status["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.status["baseline_groups"] = sorted(self.tracker.initialized)
            self.status["archived_messages"] = self.archive.count
            tmp = self.base / "runtime/status.tmp"
            tmp.write_text(json.dumps(self.status, ensure_ascii=False, indent=2))
            tmp.replace(self.base / "runtime/status.json")
        self.live.flush()


    def apply_pending_config(self):
        if self.pending_config is None:
            return
        if any((self.future, self.ready_reply, self.verifying, self.style_future)):
            return
        updated = self.pending_config
        self.pending_config = None
        errors, warnings = config_check.check(config_check.apply_defaults(updated))
        if errors:
            self.log("新配置有误，已保留原配置：" + "；".join(errors))
            self.set_status("配置有误，已保留原配置：" + errors[0], "error")
            return
        self.config_warnings = warnings
        self.status["config_warnings"] = warnings
        for warning in warnings:
            self.log("配置提示：" + warning)
        previous_model = self.config.get("ai", {}).get("model", "")
        self.config.clear()
        self.config.update(updated)
        self.model.dropped.clear()              # another provider may take what the old one rejected
        self.style_model.dropped.clear()
        self.image_generator.config = self.config.get("image_generation", {})
        quota_config = self.config.get("image_generation", {})
        self.image_quota.max_per_24h = quota_config.get("max_per_24h", 2)
        self.image_quota.unlimited = set(quota_config.get("unlimited_senders", ()))
        self.wake_interval = self.config.get("wake_seconds", 30)
        model = self.config.get("ai", {}).get("model", "")
        self.status["model"] = model
        if model != previous_model:
            self.log(f"回复模型已热切换：模型={model}")
            self.set_status(f"已切换到 {model or 'AI'}，继续监听", "paused" if self.paused else "listening")
        else:
            self.log("模型配置已热应用")
            self.set_status("配置已热应用，继续监听", "paused" if self.paused else "listening")

    def log(self, message):
        self.live.note(message)
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
        path = self.base / "runtime/bridge.log"
        try:
            if path.exists() and path.stat().st_size > LOG_LIMIT_BYTES:
                path.replace(path.with_name("bridge.log.1"))  # keep one previous generation
            with path.open("a") as handle:
                handle.write(line)
        except OSError:
            pass

    def set_status(self, message, state=None):
        with self.status_lock:
            changed = self.status.get("message") != message
            self.status["message"] = message
            if state:
                self.status["state"] = state
            self.live_engine()
            self.save()
        if changed:
            self.native.call("status", text=message)

    def handle_pause(self, paused):
        if not paused and not ai_configured(self.config.get("ai")):
            self.log("AI 供应商还没配置完整，没有开始")
            self.native.call("pause", text="还没有配置 AI 供应商：请先在设置 → AI 供应商里填好接口地址、API Key 和模型名称")
            paused = True
        self.epoch += 1
        self.uncertain = None             # the user paused or resumed by hand: no automatic resume pending
        dropped = []
        if self.failed:
            dropped.append(f"待重试的一批消息（{len(self.failed[1])} 条，会话={self.failed[0]}）")
        if self.ready_reply:
            dropped.append("一条待发送的回复")
        if self.verifying:
            dropped.append("一条正在确认的发送")
        waiting = sum(len(messages) for messages in self.tracker.pending.values())
        if waiting:
            dropped.append(f"{waiting} 条等待合并的消息")
        self.log(("已暂停" if paused else "开始运行，重新建立消息基线") + ("；丢弃：" + "、".join(dropped) if dropped else ""))
        self.paused = paused
        self.live_finish("cancelled", "已暂停")
        self.drop_topic_preview("已暂停，预览作废", status=False)
        self.model.cancel()
        self.style_model.cancel()
        if self.style_future:
            self.style_future.cancel()
            self.style_future = self.style_job = None
        for job in (self.ready_reply, self.verifying):
            if job and job.get("image_path"):
                try:
                    Path(job["image_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
        self.ready_reply = self.verifying = self.failed = None
        self.manual_proactive_group = None
        self.tracker = Tracker(self.archive)
        self.previews.clear()
        self.sidebar_started = False
        self.initial_new.clear()
        self.changed_since.clear()
        self.content_wait.clear()
        self.image_load_wait.clear()
        self.secondary_visit.clear()
        self.discard_prepared_images()
        self.visited.clear()
        self.drafts.clear()
        self.retry_after = 0
        self.failure_count = 0
        self.next_poll = 0
        self.set_status("已暂停" if paused else f"正在记录 {len(self.config['groups'])} 个群的现有消息", "paused" if paused else "starting")

    def run(self):
        try:
            while True:
                try:
                    event = self.native.events.get(timeout=0.3)
                except queue.Empty:
                    event = {}
                if event.get("event") == "shutdown":
                    break
                if event.get("event") == "paused":
                    self.handle_pause(event["paused"])
                if event.get("event") == "configure" and isinstance(event.get("config"), dict):
                    self.pending_config = event["config"]
                    self.log("收到模型热切换请求；等待当前回复与发送确认完成")
                    self.set_status("模型切换等待当前回复完成", "switch_pending")
                if event.get("event") == "style_revert":
                    self.revert_style_compression(event.get("group"))
                if event.get("event") == "feedback_revert":
                    self.revert_feedback_round()
                if event.get("event") == "topic_prefs_revert":
                    self.revert_topic_preferences()
                if event.get("event") == "proactive_now":
                    self.request_proactive(event.get("group"))
                if event.get("event") == "topic_choice":
                    self.choose_topic(event.get("index"))
                self.check_topic_preview()
                self.check_topic_outcomes()
                self.check_auto_resume()
                if time.monotonic() >= self.next_cleanup:
                    self.next_cleanup = time.monotonic() + CLEANUP_INTERVAL
                    self.cleanup_generated_images()
                if self.future and self.future.done():
                    self.collect()
                if not self.paused:
                    self.check_style_summary()
                self.apply_pending_config()
                if not self.paused and time.monotonic() >= self.next_poll:
                    self.next_poll = time.monotonic() + self.config["poll_seconds"]
                    try:
                        self.poll()
                    except Exception as exc:
                        self.set_status(f"检查失败：{type(exc).__name__} {str(exc)[:140]}".strip(), "error")
                    self.live_sync()
                    self.save()  # 心跳：即使没有任何状态变化也刷新 updated_at，便于判断程序是否还在工作
                if not self.paused:
                    self.check_manual_proactive()
                    self.check_proactive()
                elif time.monotonic() >= self.next_poll:
                    self.next_poll = time.monotonic() + 5
                    self.save()  # 暂停时也写心跳，界面据此判断后台是否存活
        finally:
            self.model.cancel()
            self.style_model.cancel()
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.style_pool.shutdown(wait=False, cancel_futures=True)

    def collect(self):
        future, self.future = self.future, None
        group, fresh = self.inflight
        self.inflight = None
        try:
            self._accept(future.result(), group, fresh)
        except Exception as exc:
            self._on_failure(exc, group, fresh)

    def _accept(self, reply, group, fresh):
        """Take a finished model/image job: book-keeping first, then route by kind."""
        if self.paused or self.flight_epoch != self.epoch:
            self.live_finish("cancelled", "已暂停或配置切换，结果已丢弃")
            if reply.get("image_path"):
                try:
                    Path(reply["image_path"]).unlink(missing_ok=True)
                except OSError:
                    pass
            return
        self._apply_suffix(reply)
        self.failure_count = 0
        self._record_usage(reply)
        kind = reply.get("kind")
        if kind == "browser":
            self._record_browser(reply)
        elif kind == "proactive":
            self._on_proactive(reply, group)
            return
        elif kind == "proactive_preview":
            self._on_topic_preview(reply, group)
            return
        elif kind == "image_moderation":
            self._on_moderation(reply, group, fresh)
            return
        self._on_reply(reply, group)

    def _apply_suffix(self, reply):
        """The owner's suffix mark for AI replies (ai.suffix, e.g. "～AI") goes after the reply, never glued to a link."""
        if not self.config.get("ai", {}).get("suffix_enabled", True):
            return
        suffix = str(self.config.get("ai", {}).get("suffix") or "")
        if not suffix or not isinstance(reply.get("reply"), str):
            return
        text = reply["reply"].rstrip()
        if text and not text.endswith(suffix):
            reply["reply"] = text + (" " if re.search(r"https?://\S*$", text) else "") + suffix

    def _record_usage(self, reply):
        timing = reply.get("usage", {}).get("timing")
        if timing and (reply.get("seconds") or 0) >= SLOW_REQUEST_SECONDS:
            self.log(f"请求偏慢（{reply['seconds']:.1f}s）：请求体 {timing['request_mb']}MB"
                     f"（含 {timing['images']} 张图）；等待响应 {timing['response_seconds']}s")
        self.status["input_tokens"] += reply.get("usage", {}).get("input_tokens", 0)
        self.status["output_tokens"] += reply.get("usage", {}).get("output_tokens", 0)
        self.daily.add("input_tokens", reply.get("usage", {}).get("input_tokens", 0) or 0)
        self.daily.add("output_tokens", reply.get("usage", {}).get("output_tokens", 0) or 0)
        if reply.get("seconds"):
            self.daily.add("model_seconds", reply["seconds"])
            self.daily.add("timed_calls")
        self.status["last_inference_seconds"] = reply.get("seconds")
        self.live.update(self.live_turn, thoughts=reply.get("thoughts"), tokens={
            "input": reply.get("usage", {}).get("input_tokens", 0),
            "output": reply.get("usage", {}).get("output_tokens", 0), "seconds": reply.get("seconds")})

    def _record_browser(self, reply):
        self.status["model_calls"] += max(0, reply["browser_calls"] - 1)
        self.status["last_browser"] = {"model": self.config.get("ai", {}).get("model", ""), "actions": reply["actions"], "video_frames": reply.get("video_frames", 0)}

    def _on_moderation(self, reply, group, fresh):
        sender = reply["sender"]
        self.status["last_image_moderation"] = {
            "group": group, "requester": sender, "allowed": reply["allowed"],
            "backend": reply["backend"], "model": reply["model"], "reason": reply["reason"],
        }
        self.live.update(self.live_turn, decision={"should_reply": reply["allowed"], "reason": reply["reason"],
                                                   "model": reply["model"], "seconds": reply.get("seconds")})
        self.live.step(self.live_turn, "ready", "审核通过" if reply["allowed"] else "审核未通过，回复说明")
        if reply["allowed"]:
            source = next(message for message in reversed(fresh) if image_generation_request(message, self.config))
            self.ready_reply = {
                "kind": "text", "group": group, "text": f"@{sender} 开始生成，请稍等", "created": time.monotonic(),
                "after_image_generation": {"group": group, "sender": sender, "prompt": reply["prompt"],
                                           "message_id": source["id"], "fresh": fresh},
            }
            self.log(f"图片请求审核通过，等待发送开始提示：群={group} 请求者={sender}")
            self.set_status("图片请求审核通过，等待发送开始提示", "reply_ready")
        else:
            self.ready_reply = {"kind": "text", "group": group, "text": f"@{sender} {reply['reply']}", "created": time.monotonic()}
            self.log(f"图片请求被拒绝：群={group} 请求者={sender} 原因={reply['reason']}")
            self.set_status("图片请求未通过审核，等待发送回复", "reply_ready")
        return

    def _on_reply(self, reply, group):
        """A decision (and possibly a reply or generated image) from the chat model."""
        if reply.get("kind") == "browser":
            self.live.update(self.live_turn, browser=[{"action": a.get("action"), "url": a.get("url"), "error": a.get("error")}
                                                      for a in reply.get("actions", [])][:12],
                             decision={"should_reply": bool(reply["reply"]), "reason": "浏览器任务", "model": reply.get("model"),
                                       "reasoning_effort": reply.get("reasoning_effort")})
        if reply.get("kind") not in ("browser", "proactive", "image_moderation"):
            self.status["last_decision"] = {"group": group, "should_reply": reply.get("should_reply", False),
                                            "model": reply.get("model", ""), "reason": reply.get("reason", "")}
            self.live.update(self.live_turn, decision={**self.status["last_decision"], "seconds": reply.get("seconds")})
            if reply.get("should_reply"):
                self.live.update(self.live_turn, reply={"model": reply.get("model"), "reason": reply.get("reason", ""),
                                                        "seconds": reply.get("seconds"), "text": reply.get("reply", "").strip()})
        if reply.get("image_path"):
            self.image_quota.record(reply["mention"])
            remaining = self.image_quota.remaining(reply["mention"])
            self.status["last_generated_image"] = {
                "group": group, "requester": reply["mention"], "model": self.config["image_generation"]["model"],
                "size": self.config["image_generation"].get("size", "1024*1024"), "remaining": remaining,
            }
            self.log(f"图片生成完成：群={group} 请求者={reply['mention']} 尺寸={reply.get('width')}x{reply.get('height')}")
            self.ready_reply = {"kind": "image", "group": group, "text": f"@{reply['mention']}", "mention": reply["mention"], "image_path": reply["image_path"], "created": time.monotonic()}
            self.live.update(self.live_turn, reply={"text": f"[图片] @{reply['mention']}", "seconds": reply.get("seconds")})
            self.live.step(self.live_turn, "ready", "图片已生成，等待发送")
            self.set_status("图片已生成，等待发送", "reply_ready")
        elif reply["should_reply"]:
            self.log(f"决定回复：群={group} 原因={reply['reason']}")
            self.live.step(self.live_turn, "ready", "回复已生成，等待发送")
            self.status["last_generated_reply"] = {"group": group, "text": reply["reply"].strip()}
            parts = split_reply(reply["reply"], self.config.get("split_reply_min_chars", 12))
            self.ready_reply = {"group": group, "text": parts[0], "rest": parts[1:], "created": time.monotonic()}
            self.set_status("回复已生成，等待发送", "reply_ready")
        else:
            self.log(f"决定不回复：群={group} 原因={reply['reason']}")
            self.live_finish("silent", reply["reason"])
            self.daily.add("silent")
            self.set_status("已阅读新消息，本轮不接话", "listening")

    def _on_failure(self, exc, group, fresh):
        self.live.update(self.live_turn, error=str(exc)[:200] if isinstance(exc, RuntimeError) else f"{type(exc).__name__}: {str(exc)[:200]}")
        if not self.paused and self.flight_epoch == self.epoch:
            if self.status.get("last_trigger", {}).get("type") == "browser":
                self.log(f"浏览任务失败：{str(exc)[:200]}")
                self.ready_reply = {"group": group, "text": "这次浏览器任务失败了，没能完成。", "created": time.monotonic()}
                self.live.step(self.live_turn, "ready", "浏览失败，改发失败说明")
                self.set_status("浏览任务失败，等待发送说明", "reply_ready")
                return
            if self.status.get("last_trigger", {}).get("type") == "proactive":
                self.log(f"主动话题生成失败，本轮不重试：群={group} 原因={str(exc)[:220]}")
                self.live_finish("failed", "主动话题生成失败")
                self.set_status("主动话题生成失败，本轮不重试", "listening")
                return
            image_request = next((message for message in fresh if image_generation_request(message, self.config)), None)
            if image_request:
                self.log(f"图片生成失败：群={group} 原因={str(exc)[:220]}")
                self.live.step(self.live_turn, "ready", "图片失败，改发说明")
                self.ready_reply = {"kind": "text", "group": group,
                                    "text": f"@{image_request['sender']} 图片请求这次没处理成功，稍后再试。",
                                    "created": time.monotonic()}
                self.set_status("图片生成失败，等待发送说明", "reply_ready")
                return
            self.failure_count += 1
            self.daily.add("failed")
            if re.search(r"HTTP (401|403|404)", str(exc)):
                # a wrong key, address or model name will not fix itself: stop now and say so
                self.paused = True
                self.live_finish("failed", "AI 接口拒绝了请求，已暂停")
                self.log(f"AI 接口拒绝了请求，已暂停：{str(exc)[:200]}")
                self.native.call("pause", text="AI 接口拒绝了请求（" + ("API Key 不对或没有权限" if re.search(r"HTTP 40[13]", str(exc)) else "接口地址或模型名称不对")
                                  + "）：请在设置 → AI 供应商里检查，保存配置后点击“开始”重试")
                self.set_status("AI 接口拒绝了请求，已暂停", "model_error")
                return
            if self.failure_count >= 3:
                if any(addressed_to_self(message, self.config) for message in fresh):
                    self.failure_count = 0
                    self.ready_reply = {"group": group, "text": "看到了，但模型暂时没接通，这条还答不了。",
                                        "created": time.monotonic()}
                    self.log(f"明确 @ 的模型调用连续失败，等待发送故障说明：群={group}")
                    self.live.step(self.live_turn, "ready", "模型连续失败，改发故障说明")
                    self.set_status("模型调用失败，等待发送故障说明", "reply_ready")
                    return
                self.paused = True
                self.live_finish("failed", "模型连续失败 3 次，已自动暂停")
                self.log(f"模型连续失败 3 次，已自动暂停（最后一次错误：{str(exc)[:200]}）")
                self.native.call("pause", text="AI 连续失败 3 次，已暂停；请检查网络和 AI 供应商设置，保存后点击“开始”重试")
                self.set_status("模型连续失败 3 次，已暂停", "model_error")
                return
            if not self.config.get("retry_failed_batch", True):
                self.live_finish("failed", f"第 {self.failure_count} 次失败，已跳过这批消息")
                self.log(f"模型调用失败（第 {self.failure_count} 次），已跳过这批消息：群={group}：{str(exc)[:200]}")
                self.set_status("模型调用失败，已跳过：" + str(exc)[:100], "model_error")
                return
            self.live_finish("failed", f"第 {self.failure_count} 次失败，60 秒后重试")
            self.failed = (group, fresh)
            self.retry_after = time.monotonic() + 60
            self.log(f"模型调用失败（第 {self.failure_count} 次）群={group}：{str(exc)[:200]}")
            self.set_status("模型调用失败，60 秒后重试：" + str(exc)[:100], "model_error")

    def notify(self, title, text):
        """A macOS notification through the native app (best effort)."""
        try:
            self.native.call("notify", title=title, text=text)
        except Exception:
            pass

    def _maybe_follow_repeat(self, group):
        """Two or more members just sent the same short text: join in now and then (decided once per run), without
        asking the model. Those messages then do not go to the model as well."""
        probability = float(self.config.get("repeat_follow_probability", 0.5))
        text, run, joined = repeat_chain(self.tracker.history[group])
        if text is None or joined or len({m.get("sender") for m in run}) < int(self.config.get("repeat_follow_min", 2)):
            if text != self.repeat_decided.get(group):
                self.repeat_decided.pop(group, None)
            return False
        if probability <= 0 or self.repeat_decided.get(group) == text or self.is_muted(group):
            return False
        if self.paused or self.future or self.ready_reply or self.verifying:
            return False                       # busy: try again on the next read while the run is still going
        self.repeat_decided[group] = text
        if random.random() >= probability:
            self.log(f"群友在复读「{text}」，这次不跟：群={group}")
            return False
        ids = {m["id"] for m in run}
        self.tracker.pending[group] = [m for m in self.tracker.pending[group] if m["id"] not in ids]
        self.live_finish("cancelled", "被新的任务取代")
        title = self.conversation_details.get(group, {}).get("title", group)
        self.live_turn = self.live.begin(group, title, "reply", run[-4:])
        self.live.update(self.live_turn, decision={"should_reply": True, "reason": f"{len(run)} 位群友在复读，跟一句"})
        self.live.step(self.live_turn, "ready", "跟着群友复读")
        self.ready_reply = {"group": group, "text": text, "created": time.monotonic(), "kind": "repeat"}
        self.daily.add("repeats")
        self.log(f"跟着群友复读「{text}」：群={group}")
        self.set_status("跟着群友复读，等待发送", "reply_ready")
        return True

    def _stickers_as_text(self, group, messages):
        """Animated stickers (recognised from the conversation preview, remembered by id) become the text
        "[动画表情]": never copied or uploaded as pictures, and a batch of only stickers does not reach the model."""
        known = self.sticker_ids[group]
        for message in messages:
            if message.get("image_kind") == "sticker":
                known.add(message["id"])
        if len(known) > 2000:
            known.intersection_update(m["id"] for m in messages)
        return [{**m, "has_image": False, "text": "[动画表情]", "image_kind": "sticker", "content_pending": False}
                if m["id"] in known else m for m in messages]

    def is_muted(self, group):
        muted = self.config.get("muted_chats") or []
        title = self.conversation_details.get(group, {}).get("title", "")
        return bool(muted) and (group in muted or title in muted)

    def cleanup_generated_images(self, now=None):
        """Delete generated/prepared images older than ``image_retention_days`` (7 by default) from runtime/."""
        now = time.time() if now is None else now
        cutoff = now - 86400 * int(self.config.get("image_retention_days", 7))
        removed = 0
        for pattern in ("generated-*.png", "generated-*.jpg", "generated-*.webp", "image-*.jpg"):
            for path in (self.base / "runtime").glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                        removed += 1
                except OSError:
                    pass
        if removed:
            self.log(f"已清理 {removed} 张超过 {self.config.get('image_retention_days', 7)} 天的图片")
        return removed

    def user_typing(self, now=None):
        """The user typed within the last ``typing_quiet_seconds``: never bring QQ to the front then."""
        try:
            typing = bool(self.native.call("typing").get("typing"))
        except Exception:
            return False
        now = time.monotonic() if now is None else now
        if typing and now - getattr(self, "last_typing_note", -1e9) >= 60:
            self.last_typing_note = now
            self.log("你正在打字，暂不切换到 QQ")
        return typing

    def wake_qq(self, now):
        """把 QQ 置前一次以唤醒它的辅助功能树；连续无效时按退避放宽间隔，避免反复抢焦点。"""
        if now - self.last_wake < self.wake_interval:
            return
        if self.user_typing(now):
            self.last_wake = now - self.wake_interval + 5         # look again in 5 s, without growing the back-off
            return
        app = self.config.get("qq_app", "/Applications/QQ.app")
        self.last_wake = now
        try:
            subprocess.run(["open", "-a", app], timeout=10, check=False)
            self.native.call("wake")
            self.log(f"QQ 界面不可读，已尝试唤醒 {app}（下次最快 {self.wake_interval:.0f} 秒后重试）")
            self.daily.add("wakes")
        except Exception as exc:
            self.log(f"唤醒 QQ 失败：{str(exc)[:150]}")
        self.wake_interval = min(self.wake_interval * 2, self.config.get("wake_seconds_max", 600))


    def conversation_targets(self):
        if not self.config.get("reply_all_conversations"):
            return list(self.config["groups"])
        return list(dict.fromkeys(self.config["groups"] + self.visible_conversations + list(self.archive.text_counts)))

    def observe_conversations(self, data):
        previews = data["conversations"]
        self.visible_conversations = list(previews)
        changed = []
        for key, preview in previews.items():
            if key not in self.previews:
                if self.sidebar_started:
                    self.initial_new[key] += 1
                    self.changed_since.setdefault(key, time.monotonic())
                    changed.append(key)
                self.previews[key] = preview
            elif self.previews[key] != preview:
                if self.image_load_wait.get(key, {}).get("timed_out"):
                    self.image_load_wait.pop(key, None)
                self.initial_new[key] += 1
                self.changed_since.setdefault(key, time.monotonic())
                changed.append(key)
                self.previews[key] = preview
        self.sidebar_started = True
        dirty = False
        for key, detail in data.get("conversation_details", {}).items():
            old = self.conversation_details.get(key, {})
            detail = dict(detail)
            if detail.get("kind") == "unknown" and old.get("kind"):
                detail["kind"] = old["kind"]
            if detail != old:
                self.conversation_details[key] = detail
                dirty = True
        if dirty:
            tmp = self.conversations_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.conversation_details, ensure_ascii=False, indent=2))
            os.chmod(tmp, 0o600)
            tmp.replace(self.conversations_path)
        self.status["conversations"] = self.conversation_details
        self.status["reply_all_conversations"] = bool(self.config.get("reply_all_conversations"))
        return changed

    def defer_image_arrival(self, group, now):
        waiting = self.image_load_wait[group]
        if not waiting.get("timed_out"):
            self.log(f"图片消息加载超时，结束本次等待，稍后重新查看：会话={group}")
        waiting["timed_out"] = True
        self.unavailable_until[group] = now + 60

    def discard_prepared_images(self, group=None):
        groups = [group] if group is not None else list(self.prepared_images)
        for key in groups:
            for path in self.prepared_images.pop(key, {}).values():
                Path(path).unlink(missing_ok=True)

    def prepare_pending_images(self, group, loading_batch=()):
        candidates = list({m["id"]: m for m in self.tracker.pending[group] + list(loading_batch)
                           if m.get("has_image")}.values())[:3]
        if not candidates:
            return
        now = time.monotonic()
        waiting = self.image_load_wait.setdefault(group, {"started": now, "awaiting_row": False})
        secondary = group not in self.config["groups"]
        if secondary and now - self.secondary_visit.get(group, now) < 3:
            return
        if waiting.get("awaiting_row") or now < waiting.get("retry_after", 0):
            return
        for message in candidates:
            mid = message["id"]
            if mid in self.prepared_images[group]:
                continue
            if mid in waiting.get("errors", {}) and (secondary or time.monotonic() - waiting["started"] >= IMAGE_LOAD_SECONDS):
                continue
            result = self.native.call("capture_image", group=group, message_id=mid)
            if result.get("path"):
                self.prepared_images[group][mid] = result["path"]
                waiting.get("errors", {}).pop(mid, None)
                self.log(f"图片已复制暂存，等待消息合并与判断：会话={group} 消息={mid}")
            else:
                waiting.setdefault("errors", {})[mid] = result.get("error", "image_unavailable")
                if secondary:
                    self.tracker.pending[group] = [m for m in self.tracker.pending[group] if m["id"] != mid]
                    self.log(f"切换后3秒复制失败，跳过图片：会话={group} 消息={mid} 原因={result.get('error', 'image_unavailable')}")
                else:
                    waiting["retry_after"] = min(waiting["started"] + IMAGE_LOAD_SECONDS, time.monotonic() + 1)

    def poll(self):
        now = time.monotonic()
        snapshot = self.native.call("snapshot")
        data = parse_snapshot(snapshot, self.config)
        if data.get("error"):
            labels = {"accessibility_permission": "需要开启辅助功能权限", "account_mismatch": "QQ 账号不是测试账号，已停止处理", "qq_window_missing": "等待 QQ 主窗口"}
            self.set_status(labels.get(data["error"], data["error"]), "waiting")
            # QQ 的辅助功能树是惰性开启的：退到后台后可能整个窗口都不再暴露，
            # 需要重新置前一次才会恢复。这里按退避策略尝试唤醒。
            if data["error"] == "qq_window_missing":
                self.wake_qq(now)
            # 界面暂时读不到，不等于消息没有发出去；只有超过绝对上限才判定失败。
            self.expire_verification(now)
            return
        self.wake_interval = self.config.get("wake_seconds", 30)
        self.observe_conversations(data)
        group = data["group"]
        targets = self.conversation_targets()
        ready_images = []
        secondary = group in targets and group not in self.config["groups"]
        for other in list(self.secondary_visit):
            if other != group:
                self.secondary_visit.pop(other, None)
        if secondary:
            data = self._settle_secondary(group, data, now)
            if data is None:
                return
        if self._wait_for_messages(group, data, targets, secondary, now):
            return
        ready_images = self._ingest(group, data, targets, secondary, now)
        if self._deliver(now, group, data):
            return
        if self._start_work(now, group, targets, ready_images, secondary):
            return
        self._navigate(now, group, targets, data)

    def _settle_secondary(self, group, data, now):
        """First look at another group/private chat: wait 3 s for QQ to render, then re-read it
        (and copy a newest image if the sidebar preview says one arrived). None = skip this poll."""
        if not (self.initial_new[group] or self.tracker.pending[group]):
            return data
        started = self.secondary_visit.setdefault(group, now)
        if now - started < 3:
            primary = next((g for g in self.config["groups"] if self.initial_new[g] or self.tracker.pending[g] or (self.ready_reply and self.ready_reply["group"] == g)), None)
            if primary:
                self.select(primary)
            else:
                self.set_status("已切到聊天，等待3秒后读取图片", "waiting")
            return None
        self.image_load_wait.pop(group, None)
        self.content_wait[group].clear()
        # Read again at the deadline: the preceding snapshot may have been taken while QQ was rendering.
        refreshed = parse_snapshot(self.native.call("snapshot"), self.config)
        if refreshed.get("group") != group or refreshed.get("error"):
            self.initial_new.pop(group, None)
            self.log(f"切换后3秒目标会话不可读，跳过本次通知：会话={group}")
            primary = next(iter(self.config["groups"]), None)
            if primary:
                self.select(primary)
            return None
        data = refreshed
        if self.initial_new[group] and data["conversations"].get(group, "").rstrip().endswith("[图片]"):
            cached = next(((mid, path) for mid, path in self.prepared_images[group].items()), None)
            result = ({"message_id": cached[0], "path": cached[1]} if cached else
                      self.native.call("capture_latest_image", group=group,
                                       exclude_ids=list(self.tracker.seen[group])))
            if result.get("path") and result.get("message_id"):
                mid = result["message_id"]
                self.prepared_images[group][mid] = result["path"]
                picture = next((m for m in data["messages"] if m["id"] == mid), None)
                if picture is None:
                    picture = {"id": mid, "sender": self.conversation_details.get(group, {}).get("title", group),
                               "text": "", "self": False, "bot": False}
                    data["messages"].append(picture)
                picture["has_image"] = True
                picture["content_pending"] = False
                self.log(f"切换后3秒已直接复制最新图片：会话={group} 消息={mid}")
            else:
                self.initial_new.pop(group, None)
                self.log(f"切换后3秒直接复制未成功，跳过本次通知：会话={group} 原因={result.get('error', 'image_unavailable')}")
                primary = next(iter(self.config["groups"]), None)
                if primary:
                    self.select(primary)
                return None
        if not data.get("messages_ready", True):
            self.initial_new.pop(group, None)
            self.log(f"切换后3秒消息仍不可读，跳过本次通知：会话={group}")
            primary = next(iter(self.config["groups"]), None)
            if primary:
                self.select(primary)
            return None
        return data

    def _wait_for_messages(self, group, data, targets, secondary, now):
        """True when the chat is not readable yet and this poll should end."""
        if not secondary and group in targets and self.initial_new[group] and data["conversations"].get(group, "").rstrip().endswith("[图片]"):
            self.image_load_wait.setdefault(group, {"started": now, "awaiting_row": True})
        if group in targets and not data.get("messages_ready", True) and now >= self.unavailable_until.get(group, 0):
            image_wait = self.image_load_wait.get(group)
            if image_wait and now - image_wait["started"] >= IMAGE_LOAD_SECONDS:
                self.defer_image_arrival(group, now)
            else:
                self.set_status("等待当前聊天的消息加载完整", "waiting")
                if not image_wait:
                    self.select(group)
                return True
        return False

    def _ingest(self, group, data, targets, secondary, now):
        """Merge the visible messages into the tracker; returns image messages that are ready to copy."""
        ready_images, fresh = [], []
        if not (group in targets and data.get("messages_ready", True)):
            return ready_images
        data["messages"] = self._stickers_as_text(group, data["messages"])
        initial_count = self.initial_new[group]
        eligible = data["messages"] if group in self.tracker.initialized else data["messages"][-initial_count:] if initial_count else []
        image_wait = self.image_load_wait.get(group)
        if image_wait and image_wait.get("awaiting_row"):
            tail = data["messages"][-initial_count:] if initial_count else eligible
            queued_image_ids = {m["id"] for m in self.tracker.pending[group] if m.get("has_image")}
            if (any(m.get("has_image") and not m.get("self") and m["id"] not in self.tracker.seen[group] for m in tail)
                    or any(m.get("has_image") and m["id"] in queued_image_ids for m in data["messages"])):
                image_wait["awaiting_row"] = False
            elif now - image_wait["started"] >= IMAGE_LOAD_SECONDS:
                self.defer_image_arrival(group, now)
        waiting = self.content_wait[group]
        for message in eligible:
            if not secondary and message.get("content_pending") and not message.get("self") and not message.get("bot") and message["id"] not in self.tracker.seen[group]:
                waiting.setdefault(message["id"], image_wait["started"] if image_wait else now)
        messages = []
        for message in data["messages"]:
            if secondary and message.get("content_pending"):
                self.tracker.seen[group].add(message["id"])
                continue
            mid = message["id"]
            if mid in waiting:
                if not message.get("content_pending"):
                    waiting.pop(mid)
                elif now - waiting[mid] < IMAGE_LOAD_SECONDS:
                    continue
                else:
                    waiting.pop(mid)
                    message = {**message, "content_pending": False}
                    self.log(f"消息内容加载超时，本条不触发回复：会话={group} 消息={mid}")
            messages.append(message)
        for mid, started in list(waiting.items()):
            if now - started >= IMAGE_LOAD_SECONDS:
                waiting.pop(mid)
        if image_wait and image_wait.get("awaiting_row"):
            pass  # the image row has not appeared yet; ingest later
        elif waiting:
            if group in self.tracker.initialized:
                fresh = self.tracker.ingest(group, messages, now, 0, self._merge_waits())
            else:
                ready_images = [m for m in eligible if m.get("has_image") and not m.get("self") and m["id"] not in self.tracker.seen[group]]
        else:
            fresh = self.tracker.ingest(group, messages, now, self.initial_new.pop(group, 0), self._merge_waits())
        if fresh and self.topic_watches:
            self._watch_reactions(group, fresh, now)
        self._maybe_follow_repeat(group)
        self.visited[group] = now
        self.drafts[group] = data.get("draft", "")
        self.select_started.pop(group, None)
        self.previews[group] = data["conversations"].get(group)
        return ready_images


    def _start_work(self, now, group, targets, ready_images, secondary):
        """Prepare images and start the next model job if one is due. True when this poll should end."""
        if group in targets:
            if ready_images:
                self.prepare_pending_images(group, ready_images)
            else:
                self.prepare_pending_images(group)
        if secondary:
            self.image_load_wait.pop(group, None)
        if self.failed and now >= self.retry_after and not self.future:
            failed_group, fresh = self.failed
            if group != failed_group and any(m.get("has_image") for m in fresh):
                # images can only be copied while their chat is open: go back there first
                if now - self.retry_after > FAILED_RETRY_PATIENCE:
                    self.failed = None
                    self.log(f"放弃重试失败的批次：{FAILED_RETRY_PATIENCE:.0f} 秒内没能回到该聊天读取图片：会话={failed_group}")
                else:
                    self.select(failed_group)
                    return True
            else:
                self.failed = None
                self.start_inference(failed_group, fresh)
        if not self.future and not self.failed:
            aged = self._aged_pending(now, targets)
            candidates = sorted(targets, key=lambda key: (
                0 if key in self.config["groups"] or key in aged else 1,
                self.tracker.first.get(key, now)))
            for candidate in candidates:
                mentioned = any(addressed_to_self(message, self.config) for message in self.tracker.pending[candidate])
                image_wait = self.image_load_wait.get(candidate, {})
                image_blocked = image_wait.get("awaiting_row") or now < image_wait.get("retry_after", 0)
                if not self.content_wait[candidate] and not image_blocked and self.tracker.due(candidate, now, self.config) and (mentioned or (
                        now - self.last_reply[candidate] >= self.config["cooldown_seconds"])):
                    if group != candidate:
                        self.select(candidate)
                        return True
                    fresh = self.tracker.pending.pop(candidate)
                    first_mention = next((i for i, message in enumerate(fresh)
                                          if addressed_to_self(message, self.config)), None)
                    if first_mention is not None and first_mention + 1 < len(fresh):
                        self.tracker.pending[candidate] = fresh[first_mention + 1:]
                        fresh = fresh[:first_mention + 1]
                    self.start_inference(candidate, fresh)
                    break
        return False

    def _merge_waits(self):
        """How many merge-wait periods one batch may take (``max_merge_waits``; 0 = unlimited)."""
        return self.config.get("max_merge_waits", 3)

    def _overdue_secondary(self, now):
        """Other chats (not the main groups) whose new messages have been waiting to be looked at for longer than
        ``secondary_max_wait_seconds``, oldest first. 0 keeps the strict "main group first" order."""
        limit = self.config.get("secondary_max_wait_seconds", 8)
        overdue = []
        for key, since in list(self.changed_since.items()):
            if not self.initial_new[key]:
                del self.changed_since[key]
            elif (limit > 0 and key not in self.config["groups"] and now - since >= limit
                    and now >= self.unavailable_until.get(key, 0)):
                overdue.append((since, key))
        return [key for _, key in sorted(overdue)]

    def _aged_pending(self, now, targets):
        """Other chats whose already-read messages have waited for a reply longer than the limit."""
        limit = self.config.get("secondary_max_wait_seconds", 8)
        if limit <= 0:
            return set()
        return {key for key in targets if key not in self.config["groups"] and self.tracker.pending[key]
                and now - self.tracker.first.get(key, now) >= limit}

    def _navigate(self, now, group, targets, data):
        """Decide which chat QQ should show next: pending work first, otherwise back to the main group."""
        baseline_targets = self.config["groups"] if self.config.get("reply_all_conversations") else self.visible_conversations
        uninitialized = [g for g in baseline_targets if g not in self.tracker.initialized and now >= self.unavailable_until.get(g, 0)]
        changed = [g for g in self.visible_conversations if g != group and self.initial_new[g] and now >= self.unavailable_until.get(g, 0)]
        overdue = self._overdue_secondary(now)
        changed.sort(key=lambda g: 0 if g in overdue else 1 if g in self.config["groups"] else 2)
        if self.ready_reply:
            return
        if not group:
            waiting = [g for g in targets if self.tracker.pending[g] or self.content_wait[g] or
                       (g in self.image_load_wait and not self.image_load_wait[g].get("timed_out"))]
            if waiting:
                self.select(waiting[0])
                return
        primary_changed = any(g in self.config["groups"] for g in changed)
        loading_image = group in self.image_load_wait and not self.image_load_wait[group].get("timed_out")
        # Messages merely waiting out the merge/cooldown timer must not hold the bot on this chat while
        # another chat's new messages have waited too long; image/content loading still has to finish first.
        limit = self.config.get("secondary_max_wait_seconds", 8)
        urgent = limit > 0 and any(now - self.changed_since[g] >= 2 * limit for g in overdue)   # even image loading yields
        holding = ((self.content_wait[group] or loading_image) and not urgent) or (self.tracker.pending[group] and not overdue)
        if holding and not primary_changed:
            if not self.future and not self.failed:
                self.set_status("等待图片或消息内容加载（最多10秒）" if self.content_wait[group] or group in self.image_load_wait else "当前聊天还有待处理消息，等待合并或回复冷却", "waiting")
            return
        if not changed and uninitialized:
            self.select(uninitialized[0])
            return
        if changed:
            self.select(changed[0])
        elif not self.future and not self.failed:
            primary = next((g for g in self.config["groups"] if g in data["conversations"]), None)
            if primary and group != primary:
                self.select(primary)
            self.set_status(f"主群优先 · 监听 {len(self.visible_conversations)} 个会话 · 新消息才跳转", "listening")

    def select(self, group):
        now = time.monotonic()
        if group not in self.select_started:
            if self.user_typing(now):
                return
            subprocess.run(["open", "-a", self.config.get("qq_app", "/Applications/QQ.app")], timeout=10, check=False)
            self.native.call("wake")
        since = self.select_started.setdefault(group, now)
        if now - since > 15:
            self.unavailable_until[group] = now + 60
            self.select_started.pop(group, None)
            self.status["unavailable_group"] = group
            self.set_status("会话暂时无法打开，60 秒后再检查", "waiting")
            return
        result = self.native.call("select", group=group)
        if result.get("error"):
            self.set_status("等待打开会话：" + result["error"], "waiting")

    def begin_image_generation(self, job):
        group, sender, prompt, fresh = job["group"], job["sender"], job["prompt"], job["fresh"]
        image_config = self.config["image_generation"]
        self.status["image_generation_calls"] += 1
        self.status["last_trigger"] = {"group": group, "message_ids": [job["message_id"]], "type": "image_generation"}
        self.begin_flight(group, fresh, "image", "generating", "开始生成图片", continue_turn=True)

        def generate_image():
            started = time.monotonic()
            generated = self.image_generator.generate(prompt)
            return {"should_reply": True, "image_path": generated["path"], "mention": sender,
                    "width": generated.get("width"), "height": generated.get("height"),
                    "seconds": round(time.monotonic() - started, 2)}

        self.future = self.pool.submit(generate_image)
        self.log(f"开始生成图片：群={group} 请求者={sender} 模型={image_config['model']} 尺寸={image_config.get('size', '1024*1024')}")
        self.set_status("文字提示已发送，正在生成图片", "thinking")

    def start_inference(self, group, fresh):
        if self.is_muted(group):
            self.log(f"该聊天已静音，只记录不回复：会话={group}")
            self.set_status("该聊天已静音，不回复", "listening")
            return
        if self._start_browser(group, fresh) or self._start_image_request(group, fresh):
            return
        loaded = self._load_images(group, fresh)
        if loaded is None:
            return
        images, unavailable_image_ids, fresh = loaded
        if not fresh:
            self.log(f"图片未读到，已跳过本条消息：会话={group}")
            self.set_status("图片未读到，跳过本条消息", "listening")
            return
        self._submit_reply(group, fresh, images, unavailable_image_ids)

    def _start_browser(self, group, fresh):
        """Links the group shared (or asked to open) go to the browser task. True when started."""
        browser = self.config.get("browser", {})
        request = browser_request(fresh, list(self.tracker.history[group])) if browser.get("enabled") else None
        if not request:
            return False
        self.image_load_wait.pop(group, None)
        self.discard_prepared_images(group)
        if any(addressed_to_self(message, self.config) for message in fresh):
            request["automatic"] = False
        request["recent_context"] = list(self.tracker.history[group])[-12:]
        self.status["model_calls"] += 1
        self.status["last_trigger"] = {"group": group, "message_ids": [m["id"] for m in fresh], "type": "browser"}
        self.begin_flight(group, fresh, "browser", "generating", f"打开链接 {request['url'][:80]}")
        self.future = self.pool.submit(self.model.browse, request)
        self.log(f"开始浏览器任务：{request['url'][:80]}")
        self.set_status("正在阅读链接", "thinking")
        return True

    def _start_image_request(self, group, fresh):
        """An @-mention asking for a generated picture: quota check, then content moderation. True when handled."""
        if not self.config.get("image_generation", {}).get("enabled"):
            return False
        request = next(((message, image_generation_request(message, self.config)) for message in reversed(fresh)
                        if image_generation_request(message, self.config)), None)
        if not request:
            return False
        self.image_load_wait.pop(group, None)
        self.discard_prepared_images(group)
        message, prompt = request
        sender = str(message.get("sender", "")).strip()
        if self.image_quota.remaining(sender) == 0:
            limit = self.image_quota.max_per_24h
            self.ready_reply = {"kind": "text", "group": group, "text": f"@{sender} 24小时内只能生成{limit}张图，额度恢复后再来", "created": time.monotonic()}
            self.log(f"图片生成请求超过限额：群={group} 请求者={sender}")
            self.set_status("图片生成额度已用完，等待发送提示", "reply_ready")
            return True
        self.status["model_calls"] += 1
        self.status["image_moderation_calls"] += 1
        self.status["last_trigger"] = {"group": group, "message_ids": [message["id"]], "type": "image_moderation"}
        self.begin_flight(group, fresh, "image", "judging", f"{sender} 请求生成图片，先做内容审核")
        self.future = self.pool.submit(self.model.moderate_image_request, group, sender, prompt)
        self.log(f"开始审核图片生成请求：群={group} 请求者={sender}")
        self.set_status("收到图片生成请求，正在审核", "thinking")
        return True

    def _load_images(self, group, fresh):
        """Copy the images the model should see out of QQ. Returns (images, unavailable_ids, fresh),
        or None when the images are still loading and the batch was put back."""
        images = []
        unavailable_image_ids = []
        candidates = [message for message in fresh if message.get("has_image")]
        if not candidates and any(re.search(r"图|照片|画|这张|这个|这位|[他她它]是谁|是谁|什么角色", m.get("text", "")) for m in fresh):
            history = list(self.tracker.history[group])
            fresh_ids = {m["id"] for m in fresh}
            earlier = [m for m in history[-14:] if m.get("has_image") and not m.get("self") and m["id"] not in fresh_ids]
            if earlier:
                candidates = earlier[-1:]
        if candidates:
            self.image_load_wait.setdefault(group, {"started": time.monotonic(), "awaiting_row": False})
        for message in candidates:
            if not message.get("has_image") or len(images) >= 3:
                continue
            image_wait = self.image_load_wait[group]
            previous_error = image_wait.get("errors", {}).get(message["id"])
            cached_path = self.prepared_images[group].pop(message["id"], None)
            if cached_path:
                result = {"path": cached_path}
            elif previous_error and time.monotonic() - image_wait["started"] >= IMAGE_LOAD_SECONDS:
                result = {"error": previous_error}
            else:
                result = self.native.call("capture_image", group=group, message_id=message["id"])
            if result.get("path"):
                images.append((message["id"], result["path"]))
            else:
                if result.get("error") in {"image_unavailable", "image_not_visible", "image_copy_unavailable", "image_copy_timeout", "image_clipboard_unreadable", "image_context_changed", "qq_window_missing"}:
                    now = time.monotonic()
                    image_wait = self.image_load_wait.setdefault(group, {"started": now, "awaiting_row": False})
                    image_wait.setdefault("errors", {})[message["id"]] = result["error"]
                    if group in self.config["groups"] and now - image_wait["started"] < IMAGE_LOAD_SECONDS:
                        for _, path in images:
                            Path(path).unlink(missing_ok=True)
                        image_wait["retry_after"] = now + 1
                        self.tracker.pending[group] = fresh + self.tracker.pending[group]
                        self.set_status("图片尚未就绪，等待加载重试（最多10秒）", "waiting")
                        return None
                if group not in self.config["groups"]:
                    fresh = [m for m in fresh if m["id"] != message["id"]]
                unavailable_image_ids.append(message["id"])
                detail = result.get("types", "")
                self.log(f"图片未能读取：群={group} 消息={message['id']} 原因={result.get('error', 'unknown')} 剪贴板类型={detail}")
        self.image_load_wait.pop(group, None)
        return images, unavailable_image_ids, fresh

    def _submit_reply(self, group, fresh, images, unavailable_image_ids):
        self.status["model_calls"] += 1
        self.status["decision_calls"] += 1
        self.status["last_trigger"] = {"group": group, "message_ids": [m["id"] for m in fresh]}
        profile = reply_profile_fields(self.base, self.config, group)
        self.status["reply_style_profile"] = {"file": "runtime/style-profile.json", "source_group": profile["style_profile_source"], "chars": len(profile["style_profile"]), "conversation_memory_group": group}
        self.begin_flight(group, fresh, "reply", "judging", f"读取 {len(fresh)} 条新消息，判断是否接话")
        self.future = self.pool.submit(self.model.generate, group, list(self.tracker.history[group]), fresh, images, unavailable_image_ids,
                                       progress=self.on_progress)
        self.log(f"开始判断是否回复：群={group} 新消息={len(fresh)} 条")
        self.set_status("收到新消息，正在判断是否回复", "thinking")