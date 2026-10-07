"""Style-summary scheduling for the engine."""
from __future__ import annotations
import json
import os
import time
from feedback import TOPIC_PREFERENCES, apply_round, load_preferences, load_ratings, pending_ratings, revert_round, save_preferences
from proactive import load_outcomes
from style import apply_compression, archived_style_messages, compress_samples, measured_style, revert_compression, style_length, style_limit
import fsutil


class StyleMixin:
    def save_style_state(self):
        tmp = self.base / "runtime/style-profile.tmp"
        tmp.write_text(json.dumps(self.style_state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        fsutil.replace(tmp, self.style_state_path)

    def check_style_summary(self):
        now = time.monotonic()
        if self.style_future and self.style_future.done():
            future, self.style_future = self.style_future, None
            job, self.style_job = self.style_job, None
            try:
                result = future.result()
                if job.get("kind") == "feedback":
                    self._apply_feedback_round(job, result)
                    return
                if job.get("kind") == "topics":
                    self._apply_topic_round(job, result)
                    return
                entry = self.style_state.setdefault("groups", {}).setdefault(job["group"], {})
                if job.get("kind") == "compress":
                    before = style_length(entry)
                    apply_compression(entry, result, time.strftime("%Y-%m-%d %H:%M:%S"))
                    self.save_style_state()
                    self.daily.add("style_compressions")
                    self.log(f"风格总结已写满，已压缩：群={job['group']} {before} 字 → {style_length(entry)} 字（核对 {result['attempts']} 轮，"
                             f"删去 {len(result['dropped'])} 条无依据的特点）；可在设置里撤回")
                    self.notify("风格总结已压缩", f"{before} 字 → {style_length(entry)} 字，旧版本已保存，可在设置里撤回")
                    self.save()
                    return
                if job.get("kind") == "history":
                    entry["historical_summary"] = result["summary"]
                    entry["historical_summarized_text_messages"] = job["end"]
                    entry["historical_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    entry["summary"] = result["summary"]
                    entry["summarized_text_messages"] = job["end"]
                    entry["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                entry["backend"] = result["backend"]
                entry["model"] = result["model"]
                entry["reasoning_effort"] = result["reasoning_effort"]
                self.save_style_state()
                self.status["style_summary_calls"] += 1
                self.status["last_style_summary"] = {"group": job["group"], "text_messages": job["end"], "kind": job.get("kind", "recent"), "backend": result["backend"], "model": result["model"], "reasoning_effort": result["reasoning_effort"]}
                self.status["style_summary_input_tokens"] = self.status.get("style_summary_input_tokens", 0) + result["usage"].get("input_tokens", 0)
                self.status["style_summary_output_tokens"] = self.status.get("style_summary_output_tokens", 0) + result["usage"].get("output_tokens", 0)
                label = "历史" if job.get("kind") == "history" else "近期"
                self.log(f"已更新{label}群聊风格摘要：群={job['group']} 累计文字消息={job['end']} 后端={result['backend']} 模型={result['model']} 用时={result['seconds']}s")
                self.save()
            except Exception as exc:
                if job and job.get("kind") == "topics":
                    self.topic_retry_after = now + 600
                    self.log(f"话题写法总结失败，10 分钟后再试（已有偏好不变）：{str(exc)[:200]}")
                    return
                if job and job.get("kind") == "feedback":
                    self.feedback_retry_after = now + 600
                    self.log(f"打分总结失败，10 分钟后再试（已有偏好不变）：{str(exc)[:200]}")
                    return
                if job and job.get("kind") == "compress":
                    self.style_retry_after = now + 3600
                    self.log(f"风格总结压缩没有采用（保留原版，1 小时后再试）：{str(exc)[:220]}")
                    return
                self.style_retry_after = now + 60
                self.log(f"群聊风格总结失败，60 秒后重试：{str(exc)[:180]}")
        if self.style_future:
            return
        if self._maybe_summarize_feedback(now) or self._maybe_summarize_topics(now) or now < self.style_retry_after:
            return
        batch_size = self.config.get("style_summary_every", 100)
        if self.config.get("style_backfill_history"):
            for group in self.conversation_targets():
                entry = self.style_state.setdefault("groups", {}).setdefault(group, {})
                history_end = max(entry.get("summarized_text_messages", 0) - batch_size, 0)
                start = entry.get("historical_summarized_text_messages", 0)
                if start >= history_end:
                    continue
                messages = archived_style_messages(self.archive.path, group)
                batch = messages[start:min(start + batch_size, history_end)]
                if not batch:
                    continue
                self.style_job = {"kind": "history", "group": group, "start": start, "end": start + len(batch)}
                self.style_future = self.style_pool.submit(self.style_model.summarize_style, group, entry.get("historical_summary", ""), batch, other_summary=entry.get("summary", ""))
                self.log(f"开始回填群聊历史风格摘要：群={group} 第 {start + 1}-{start + len(batch)} 条文字消息")
                return
        for group in self.conversation_targets():
            total = self.archive.text_counts[group]
            entry = self.style_state.setdefault("groups", {}).setdefault(group, {})
            if "summarized_text_messages" not in entry:
                entry["summarized_text_messages"] = max(total - batch_size, 0)
            start = entry["summarized_text_messages"]
            if total - start < batch_size:
                continue
            messages = archived_style_messages(self.archive.path, group)[start:start + batch_size]
            if len(messages) < batch_size:
                continue
            if self.config.get("style_compress_enabled", True) and style_length(entry) >= 0.95 * style_limit(self.config):
                # full: new traits no longer fit, so first rewrite it shorter (checked against real messages)
                self.style_job = {"kind": "compress", "group": group}
                current = "\n".join(str(entry.get(k, "")).strip() for k in ("historical_summary", "summary") if str(entry.get(k, "")).strip())
                self.style_future = self.style_pool.submit(self.style_model.compress_style, group, current,
                                                           compress_samples(self.archive.path, group),
                                                           int(self.config.get("style_compress_target_chars", 1200)),
                                                           measured_style(self.archive.path, group))
                self.log(f"风格总结已写满（{style_length(entry)} 字），开始压缩：群={group}")
                break
            self.style_job = {"kind": "recent", "group": group, "start": start, "end": start + batch_size}
            self.style_future = self.style_pool.submit(self.style_model.summarize_style, group, entry.get("summary", ""), messages, other_summary=entry.get("historical_summary", ""))
            self.log(f"开始总结群聊说话风格：群={group} 第 {start + 1}-{start + batch_size} 条文字消息")
            break

    def revert_style_compression(self, group=None):
        group = group or self.config.get("reply_style_group") or next(iter(self.config.get("groups", [])), "")
        entry = self.style_state.get("groups", {}).get(group, {})
        if self.style_future is not None and (self.style_job or {}).get("kind") == "compress":
            self.log("风格总结正在压缩，稍后再撤回")
            return False
        if not revert_compression(entry, time.strftime("%Y-%m-%d %H:%M:%S")):
            self.log(f"没有可撤回的风格总结压缩：群={group}")
            return False
        self.save_style_state()
        self.log(f"已撤回上次风格总结压缩：群={group}（现在 {style_length(entry)} 字）")
        self.set_status("已撤回上次风格总结压缩", "paused" if self.paused else "listening")
        return True

    # -- ratings -> long-term reply preferences ---------------------------------------------------------------------
    def _maybe_summarize_feedback(self, now):
        """Every ``feedback_summary_every`` (20) new ratings, one summarising round. True when a round was started."""
        every = int(self.config.get("feedback_summary_every", 20))
        if every <= 0 or now < getattr(self, "feedback_retry_after", 0) or now < getattr(self, "next_feedback_check", 0):
            return False
        self.next_feedback_check = now + 30
        ratings, preferences = load_ratings(self.base), load_preferences(self.base)
        pending = pending_ratings(ratings, preferences)
        if len(pending) < every:
            return False
        fresh = {k for k, _ in pending}
        older = [v for k, v in sorted(ratings.items(), key=lambda item: item[1].get("time", 0)) if k not in fresh][-20:]
        self.style_job = {"kind": "feedback", "used": pending}
        self.style_future = self.style_pool.submit(self.style_model.summarize_feedback, preferences.get("text", ""),
                                                   [v for _, v in pending], older,
                                                   int(self.config.get("feedback_summary_max_chars", 600)))
        self.log(f"已攒够 {len(pending)} 条新打分，开始总结回复偏好")
        return True

    def _apply_feedback_round(self, job, result):
        preferences = load_preferences(self.base)
        apply_round(preferences, result["text"], job["used"], time.strftime("%Y-%m-%d %H:%M:%S"))
        save_preferences(self.base, preferences)
        self.daily.add("feedback_rounds")
        changes = "；".join(result.get("changes", []))[:300] or "没有新的偏好"
        self.log(f"已根据 {len(job['used'])} 条打分更新回复偏好（第 {preferences['rounds']} 轮）：{changes}")
        if result.get("removed"):
            self.log("总结里有 %d 条像“内容”而不是“表达方式”，已删掉：%s" % (len(result["removed"]), "；".join(result["removed"])[:400]))
        self.notify("回复偏好已更新", f"根据 {len(job['used'])} 条打分总结了一轮，可在设置里查看或撤回")

    def revert_feedback_round(self):
        if (self.style_job or {}).get("kind") == "feedback":
            self.log("正在总结打分，稍后再撤回")
            return False
        preferences = load_preferences(self.base)
        if not revert_round(preferences, time.strftime("%Y-%m-%d %H:%M:%S")):
            self.log("没有可撤回的打分总结")
            return False
        save_preferences(self.base, preferences)
        self.log("已撤回上一轮打分总结（那一轮用到的打分会在下次重新总结）")
        return True

    # -- how topics were received -> what to do when starting one -----------------------------------------------------
    def _maybe_summarize_topics(self, now):
        """Every ``topic_summary_every`` (20) topics that were clearly received well or ignored, one summarising round
        about *how* openings should be written (never what to talk about). True when a round was started."""
        every = int(self.config.get("topic_summary_every", 20))
        if (every <= 0 or not self.config.get("proactive_smart", True) or now < getattr(self, "topic_retry_after", 0)
                or now < getattr(self, "next_topic_check", 0)):
            return False
        self.next_topic_check = now + 60
        outcomes = {k: v for k, v in load_outcomes(self.base).items() if v.get("rating") in ("good", "bad")}
        preferences = load_preferences(self.base, TOPIC_PREFERENCES)
        pending = pending_ratings(outcomes, preferences)
        if len(pending) < every:
            return False
        fresh = {k for k, _ in pending}
        older = [v for k, v in sorted(outcomes.items(), key=lambda item: item[1].get("time", 0)) if k not in fresh][-20:]
        self.style_job = {"kind": "topics", "used": pending}
        self.style_future = self.style_pool.submit(self.style_model.summarize_topics, preferences.get("text", ""),
                                                   [v for _, v in pending], older, int(self.config.get("topic_summary_max_chars", 500)))
        self.log(f"已攒够 {len(pending)} 条有明确反应的话题，开始总结开场的写法偏好")
        return True

    def _apply_topic_round(self, job, result):
        preferences = load_preferences(self.base, TOPIC_PREFERENCES)
        apply_round(preferences, result["text"], job["used"], time.strftime("%Y-%m-%d %H:%M:%S"))
        save_preferences(self.base, preferences, TOPIC_PREFERENCES)
        self.daily.add("topic_rounds")
        self.log(f"已根据 {len(job['used'])} 条话题的反应更新开场写法偏好（第 {preferences['rounds']} 轮）："
                 + ("；".join(result.get("changes", []))[:300] or "没有新的偏好"))
        if result.get("removed"):
            self.log("总结里有 %d 条像“内容”而不是“写法”，已删掉：%s" % (len(result["removed"]), "；".join(result["removed"])[:400]))

    def revert_topic_preferences(self):
        if (self.style_job or {}).get("kind") == "topics":
            self.log("正在总结话题写法，稍后再撤回")
            return False
        preferences = load_preferences(self.base, TOPIC_PREFERENCES)
        if not revert_round(preferences, time.strftime("%Y-%m-%d %H:%M:%S")):
            self.log("没有可撤回的话题写法总结")
            return False
        save_preferences(self.base, preferences, TOPIC_PREFERENCES)
        self.log("已撤回上一轮话题写法总结")
        return True

