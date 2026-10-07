"""Proactive topics: when to post, and what came of it."""
from __future__ import annotations
import random
import time

from proactive import (hour_is_alive, hour_profile, load_topic_state, save_outcome, save_topic_state, topic_label,
                       topics_sent_today)
from reply_shape import split_reply

MAX_BACKOFF_SECONDS = 24 * 3600
PREVIEW_SECONDS = 15 * 60          # how long the openings wait for the owner; after that the group has moved on
CHOSEN_WAIT_SECONDS = 180          # a chosen opening gives up if the send slot stays busy this long
DECLINED_SECONDS = 3600            # how long turned-down openings are kept in mind so the next batch differs


class ProactiveMixin:
    def check_proactive(self):
        if not self.config.get("proactive_enabled", False):
            return
        if self.manual_proactive_group or self.topic_preview or self.future or self.ready_reply or self.verifying or self.failed:
            return
        now = time.monotonic()
        idle_seconds = self.config.get("proactive_idle_seconds", 1800)
        probability = self.config.get("proactive_probability", 0.5)
        for group in self.config["groups"]:
            activity = self.tracker.last_member_activity.get(group)
            if activity is None or self.proactive_handled_activity.get(group) == activity:
                continue
            if now - activity < idle_seconds or self.tracker.pending[group] or self.drafts.get(group, "").strip():
                continue
            allowed, why = self._proactive_gate(group, now - activity)
            if not allowed:
                self._note_gate(group, why, now)       # not marked as handled: it is looked at again when the time is right
                continue
            self.proactive_handled_activity[group] = activity
            if self.is_muted(group):
                continue
            if random.random() >= probability:
                self.log(f"群聊沉默已达阈值，本轮不主动开场：群={group}")
                continue
            self.start_proactive(group, manual=False)
            self.log(f"群聊沉默已达阈值：群={group} 沉默={now - activity:.0f}s")
            return

    def request_proactive(self, group):
        if self.paused or group not in self.config["groups"] or self.is_muted(group):
            return
        if self.manual_proactive_group:
            return
        if self.topic_preview:
            self.log("上一组话题预览还没处理，先在状态窗或弹窗里选一条（或都不发）")
            return
        if ((self.inflight and self.inflight[0] == group and self.status.get("last_trigger", {}).get("type") == "proactive") or
                (self.ready_reply and self.ready_reply.get("kind") == "proactive" and self.ready_reply["group"] == group) or
                (self.verifying and self.verifying.get("kind") == "proactive" and self.verifying["group"] == group)):
            return
        self.manual_proactive_group = group
        self.log(f"收到手动主动话题请求：群={group}")
        self.set_status("已排队，等待在当前群发起话题", "waiting")

    def check_manual_proactive(self):
        group = self.manual_proactive_group
        if not group or self.future or self.ready_reply or self.verifying or self.failed:
            return
        if group not in self.tracker.initialized or any(self.tracker.pending.values()):
            return
        if self.drafts.get(group, "").strip():
            return
        self.manual_proactive_group = None
        self.start_proactive(group, manual=True)

    def start_proactive(self, group, manual=False):
        if manual:
            activity = self.tracker.last_member_activity.get(group)
            if activity is not None:
                self.proactive_handled_activity[group] = activity
        self.status["model_calls"] += 1
        self.status["proactive_calls"] += 1
        self.status["last_trigger"] = {"group": group, "type": "proactive", "manual": manual}
        self.begin_flight(group, [], "proactive", "generating", "手动触发主动话题" if manual else "群聊沉默，主动开场")
        self.future = self.pool.submit(
            self.model.generate_proactive, group, list(self.tracker.history[group]),
            progress=self.on_progress, manual=manual, declined=self._declined_topics() if manual else (),
        )
        self.log(f"开始生成{'手动' if manual else '定时'}主动话题：群={group}")
        self.set_status("正在生成主动话题", "thinking")

    # -- what is written, and who picks it ----------------------------------------------------------------------
    def _on_proactive(self, reply, group):
        """An automatic topic is written (the model already picked the most natural one): queue it for sending."""
        self.status["model_calls"] += max(0, reply.get("calls", 1) - 1)
        self.status["last_proactive"] = {
            "group": group, "text": reply["reply"], "reason": reply["reason"],
            "manual": self.status.get("last_trigger", {}).get("manual", False),
            "backend": reply["backend"], "model": reply["model"], "reasoning_effort": reply["reasoning_effort"],
            "topic_domains": reply.get("topic_domains", []), "source_url": reply.get("source_url", ""),
        }
        self.live.update(self.live_turn, decision={"should_reply": True, "reason": reply["reason"], "model": reply["model"],
                                                   "reasoning_effort": reply["reasoning_effort"]},
                         reply={"text": reply["reply"], "seconds": reply.get("seconds")})
        self.log(f"主动话题已生成：群={group} 原因={reply['reason']}")
        if reply.get("candidates") and len(reply["candidates"]) > 1:
            self.log("话题候选：" + " ／ ".join(reply["candidates"])[:300] + (f"；评审：{reply['judge_reason']}" if reply.get("judge_reason") else ""))
        self._queue_topic(group, {"reply": reply["reply"], "shape": reply.get("shape", ""), "source_url": reply.get("source_url", "")},
                          "话题已生成，等待发送")

    def _queue_topic(self, group, option, note):
        text = option["reply"]
        # a topic without a link is typed the way members do, in short pieces (a link stays in one message)
        parts = [text] if option.get("source_url") else split_reply(text, self.config.get("split_reply_min_chars", 12))
        self.ready_reply = {"kind": "proactive", "group": group, "text": parts[0], "rest": parts[1:], "full_text": text,
                            "shape": option.get("shape", ""), "source_url": option.get("source_url", ""), "created": time.monotonic()}
        self.live.step(self.live_turn, "ready", note)
        self.set_status("主动话题已生成，等待发送", "reply_ready")

    def _on_topic_preview(self, reply, group):
        """The owner pressed the button: nothing is posted until he picks one of the written openings (or none)."""
        self.status["model_calls"] += max(0, reply.get("calls", 1) - 1)
        options = reply["candidates"]
        turn, self.live_turn = self.live_turn, None       # the turn stays open while he decides; other work must not cancel it
        self.topic_preview = {"group": group, "options": options, "turn": turn, "chosen": None, "created": time.monotonic(), "shown": time.time(),
                              "meta": {key: reply.get(key) for key in ("backend", "model", "reasoning_effort", "topic_domains")}}
        self.live.update(turn, decision={"should_reply": True, "reason": f"手动发起：写了 {len(options)} 条供你挑，选一条发（也可以都不发）",
                                         "model": reply["model"], "reasoning_effort": reply["reasoning_effort"]})
        self.live.step(turn, "choosing", f"写好了 {len(options)} 条，等你选")
        self._publish_preview()
        self.log(f"话题预览已生成：群={group} 共 {len(options)} 条：" + " ／ ".join(item["reply"] for item in options)[:300])
        self.notify("话题预览已生成", f"{len(options)} 条开场，点开菜单栏图标选一条发（也可以都不发）")
        self.set_status("话题预览已生成，等你选一条", "waiting")

    def _publish_preview(self):
        preview = self.topic_preview
        if not preview:
            self.live.set_preview(None)
            return
        group = preview["group"]
        self.live.set_preview({
            "turn": preview["turn"], "group": group, "title": self.conversation_details.get(group, {}).get("title", group),
            "since": preview["shown"], "expires": preview["shown"] + PREVIEW_SECONDS, "chosen": preview["chosen"],
            "options": [{"text": item["reply"], "shape": item["shape"], "reason": item["reason"], "link": bool(item["source_url"])}
                        for item in preview["options"]]})

    def choose_topic(self, index):
        """The owner's answer from the preview card: the number of the opening to post, anything else (or -1) for none."""
        preview = self.topic_preview
        if not preview or preview["chosen"] is not None:
            return
        if type(index) is int and 0 <= index < len(preview["options"]):
            preview["chosen"] = index
            preview["chosen_at"] = time.monotonic()
            self.log(f"选了第 {index + 1} 条话题：{preview['options'][index]['reply'][:40]}")
            self._publish_preview()
        else:
            self.drop_topic_preview("你选择都不发")

    def check_topic_preview(self):
        """Every tick: let an unanswered preview lapse, and post the chosen opening once the send slot is free."""
        preview = self.topic_preview
        if not preview:
            return
        now = time.monotonic()
        if preview["chosen"] is None:
            if now - preview["created"] > PREVIEW_SECONDS:
                self.drop_topic_preview("预览放了太久没有选，已作废")
            return
        if self.future or self.ready_reply or self.verifying or self.failed:
            if now - preview["chosen_at"] > CHOSEN_WAIT_SECONDS:
                self.drop_topic_preview("等了 3 分钟还没轮到发送，已作废")
            return
        if self.is_muted(preview["group"]):
            self.drop_topic_preview("这个会话已静音，没有发送")
            return
        self.topic_preview = None
        group, meta = preview["group"], preview["meta"]
        option = dict(preview["options"][preview["chosen"]])
        self._remember_declined(item["reply"] for i, item in enumerate(preview["options"]) if i != preview["chosen"])
        marked = {"reply": option["reply"], "backend": meta["backend"]}
        self._apply_suffix(marked)                                           # the line mark is added now, like for an automatic topic
        option["reply"] = marked["reply"]
        self.live_finish("cancelled", "被新的任务取代")
        self.live_turn = preview["turn"]
        self.live.set_preview(None)
        self.live.update(self.live_turn, reply={"text": option["reply"]})
        self.status["last_proactive"] = {"group": group, "text": option["reply"], "reason": option["reason"], "manual": True,
                                         "source_url": option["source_url"], **{k: v for k, v in meta.items() if v is not None}}
        self._queue_topic(group, option, f"你选了第 {preview['chosen'] + 1} 条，等待发送")

    def drop_topic_preview(self, why, status=True):
        """Nothing from the preview will be posted: close its turn and remember what was turned down."""
        preview, self.topic_preview = self.topic_preview, None
        if not preview:
            return
        self._remember_declined(item["reply"] for item in preview["options"])
        self.live.finish(preview["turn"], "cancelled", why)
        self.live.set_preview(None)
        self.log(f"话题预览作废：{why}：群={preview['group']}")
        if status and not (self.future or self.ready_reply or self.verifying):
            self.set_status("继续监听", "listening")

    def _remember_declined(self, texts):
        now = time.time()
        self.declined_topics = [(t, text) for t, text in self.declined_topics if now - t < DECLINED_SECONDS] + [(now, text) for text in texts]

    def _declined_topics(self):
        now = time.time()
        return [text for t, text in self.declined_topics if now - t < DECLINED_SECONDS][-6:]

    # -- when to post -----------------------------------------------------------------------------------------
    def _proactive_gate(self, group, idle, now_wall=None):
        """(allowed, why not) for an automatic topic: somebody is probably around (a member spoke recently, and this is a
        time of day when the group usually talks), it is not too soon after the last topic (longer when nobody answered
        the last ones) and today's limit is not used up. The manual button skips all of this."""
        c = self.config
        if not c.get("proactive_smart", True):
            return True, ""
        now_wall = time.time() if now_wall is None else now_wall
        max_idle = float(c.get("proactive_max_idle_seconds", 4 * 3600))
        if max_idle > 0 and idle > max_idle:
            return False, f"群里已经 {idle / 3600:.1f} 小时没人说话，多半没人在"
        hour = time.localtime(now_wall).tm_hour
        if not hour_is_alive(hour_profile(self.archive.path, group, now_wall), hour, float(c.get("proactive_min_hour_share", 0.25))):
            return False, f"{hour} 点这个群通常不活跃"
        if now_wall < load_topic_state(self.base, group).get("next_allowed", 0):
            return False, "离上一条话题太近（上一条没人理时会等得更久）"
        cap = int(c.get("proactive_max_per_day", 5))
        if cap > 0 and topics_sent_today(self.base, group, now_wall) >= cap:
            return False, f"今天已经发了 {cap} 条话题"
        return True, ""

    def _note_gate(self, group, why, now):
        key = (group, why.split("（")[0])
        if now - self.gate_notes.get(key, -1e9) >= 1800:
            self.gate_notes[key] = now
            self.log(f"暂不主动开场：{why}：群={group}")

    # -- what came of a topic ---------------------------------------------------------------------------------
    def _topic_sent(self, job, now):
        """A topic is confirmed in the chat: keep the group alone for a while and watch how it is received."""
        c = self.config
        if not c.get("proactive_smart", True):
            return
        wall, group = time.time(), job["group"]
        state = load_topic_state(self.base, group)
        state["next_allowed"] = max(state.get("next_allowed", 0), wall + float(c.get("proactive_min_gap_seconds", 3600)))
        save_topic_state(self.base, group, state)
        self.topic_watches.append({"group": group, "text": job.get("full_text") or job["text"], "shape": job.get("shape", ""),
                                   "sent_wall": wall, "sent_mono": now, "reactions": 0, "people": set()})

    def _watch_reactions(self, group, fresh, now):
        window = float(self.config.get("proactive_reaction_seconds", 600))
        for watch in self.topic_watches:
            if watch["group"] == group and now - watch["sent_mono"] <= window:
                watch["reactions"] += len(fresh)
                watch["people"].update(str(message.get("sender", "")) for message in fresh)

    def check_topic_outcomes(self, now=None):
        """Topics whose reaction window has closed: label them (good / neutral / bad), back off after ones nobody answered."""
        if not self.topic_watches:
            return
        now = time.monotonic() if now is None else now
        window = float(self.config.get("proactive_reaction_seconds", 600))
        for watch in [w for w in self.topic_watches if now - w["sent_mono"] >= window]:
            self.topic_watches.remove(watch)
            self._finish_topic(watch)

    def _finish_topic(self, watch):
        c = self.config
        reactions, people = watch["reactions"], len(watch["people"])
        label = topic_label(reactions, people, int(c.get("proactive_good_reactions", 5)))
        save_outcome(self.base, str(int(watch["sent_wall"])), {"time": watch["sent_wall"], "group": watch["group"],
                                                               "reply": watch["text"], "shape": watch["shape"],
                                                               "reactions": reactions, "people": people, "rating": label})
        state = load_topic_state(self.base, watch["group"])
        if label == "bad":
            state["unanswered"] = state.get("unanswered", 0) + 1
            wait = min(float(c.get("proactive_backoff_seconds", 7200)) * 2 ** (state["unanswered"] - 1), MAX_BACKOFF_SECONDS)
            state["next_allowed"] = max(state.get("next_allowed", 0), watch["sent_wall"] + wait)
        else:
            state["unanswered"] = 0
        save_topic_state(self.base, watch["group"], state)
        self.daily.add({"good": "topics_good", "bad": "topics_ignored"}.get(label, "topics_neutral"))
        extra = f"，下一条至少等 {(state['next_allowed'] - time.time()) / 3600:.1f} 小时" if label == "bad" else ""
        self.log(f"话题的反应：{reactions} 条消息、{people} 人 → {'有人接' if label == 'good' else '没人理' if label == 'bad' else '一般'}{extra}："
                 f"群={watch['group']} {watch['text'][:30]}")

