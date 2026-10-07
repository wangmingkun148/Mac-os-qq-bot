"""Sending queued replies and confirming them in the QQ window."""
from __future__ import annotations
from pathlib import Path
from proactive import record_proactive
from snapshot import parse_snapshot, same_text
import time


# Send results after which the outcome is unknown: pause, never resend. Value = what to tell the user.
UNCERTAIN_SEND_ERRORS = {
    "text_still_in_editor": "消息仍在输入栏",
    "text_send_context_changed": "文字发送状态无法确认",
    "image_still_in_editor": "图片仍在输入栏",
    "image_newline_instead_of_send": "回车只在输入栏里换了行、没有发送（已撤销换行，图片仍在输入栏，请手动清空）",
    "image_send_context_changed": "图片发送状态无法确认",
    "image_paste_not_ready": "图片发送状态无法确认",
    "native_timeout": "发送动作迟迟没有返回，状态无法确认",
}


class DeliveryMixin:
    def _deliver(self, now, group, data):
        """Confirm the reply that was just sent, or send the queued one. True when this poll is used up."""
        if self.verifying:
            self.check_verification(now, group, data)
            return True
        if self.ready_reply:
            job = self.ready_reply
            if now - job["created"] > 120:
                if job.get("image_path"):
                    try:
                        Path(job["image_path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
                self.ready_reply = None
                self.live_finish("abandoned", "回复等待超过 120 秒，已放弃发送")
                self.set_status("回复等待过久，已放弃本次发送", "listening")
                return True
            if group != job["group"]:
                self.select(job["group"])
                return True
            self.live.step(self.live_turn, "sending")
            if job.get("kind") == "image":
                result = self.native.call("send_image", group=group, text=job["text"], mention=job.get("mention", ""), path=job["image_path"])
            else:
                result = self.native.call("send", group=group, text=job["text"])
            if result.get("submitted"):
                self.verifying = {**job, "before": {m["id"] for m in data["messages"]}, "submitted": now, "viewed": now}
                self.ready_reply = None
                self.live.step(self.live_turn, "verifying", "已提交发送，等待 QQ 回显")
                if job.get("kind") == "image":
                    self.log(f"已提交发送图片：群={group} 请求者={job['mention']}")
                else:
                    self.log(f"已提交发送：群={group} 文本={job['text'][:60]}")
                self.set_status("正在确认 QQ 中的新回复", "verifying")
            else:
                error = result.get("error", "unknown")
                if job.get("kind") == "image" and job.get("last_error") != error:
                    self.log(f"图片发送未确认：群={group} 原因={error}")      # once per distinct reason, not every poll
                if error in UNCERTAIN_SEND_ERRORS:
                    self.ready_reply = None
                    self.paused = True
                    detail = UNCERTAIN_SEND_ERRORS[error]
                    later = self.remember_uncertain(job, {m["id"] for m in data["messages"]}, error)
                    self.live_finish("uncertain", f"{detail}，已暂停且不会重发")
                    self.log(f"{detail}，已暂停且不会自动重发：群={group}")
                    self.native.call("pause", text=f"{detail}，已暂停；" + ("稍后自动检查，确认安全就恢复（不会重发）" if later else "请检查草稿，不会自动重发"))
                    self.set_status(f"{detail}，已暂停；不会自动重发", "delivery_uncertain")
                    return True
                if job.get("last_error") != result.get("error"):
                    job["last_error"] = result.get("error")
                    self.live.step(self.live_turn, "sending", "发送受阻，稍后重试：" + str(result.get("error", "unknown")))
                self.set_status("等待发送：" + result.get("error", "unknown"), "reply_ready")
            return True
        return False

    def check_verification(self, now, group, data):
        """发送后回读 QQ 界面确认消息真的出现；确认不了就暂停，但绝不重发。"""
        job = self.verifying
        if group == job["group"]:
            job["viewed"] = now
            if job.get("kind") == "image":
                matches = [m for m in data["messages"] if m["id"] not in job["before"] and m["self"] and m.get("has_image")
                           and (not job.get("text") or job["text"] in m.get("text", ""))]
            else:
                matches = [m for m in data["messages"]
                           if m["id"] not in job["before"] and m["self"] and same_text(m["text"], job["text"])]
            if matches:
                self.last_reply[group] = now
                self.status["verified_replies"] += 1
                self.status["last_reply"] = {"group": group, "text": job["text"], "message_id": matches[-1]["id"]}
                if job.get("kind") == "proactive":
                    self.status["proactive_sent"] += 1
                    self.daily.add("topics_sent")
                    record_proactive(self.base, job)
                    self._topic_sent(job, now)
                if job.get("kind") == "image":
                    self.status["verified_images"] += 1
                    try:
                        Path(job["image_path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
                self.verifying = None
                label = "图片" if job.get("kind") == "image" else "消息"
                self.log(f"已确认发送{label}：群={group} 用时={now - job['submitted']:.1f}s 消息编号={matches[-1]['id']}")
                if job.get("rest"):
                    # the next piece of a reply that was split at its commas
                    self.ready_reply = {"group": group, "text": job["rest"][0], "rest": job["rest"][1:], "created": now}
                    self.live.step(self.live_turn, "ready", f"发送下一句（还剩 {len(job['rest'])} 句）")
                    self.set_status("继续发送下一句", "reply_ready")
                    return
                if not job.get("after_image_generation"):
                    self.live_finish("replied", f"已发送并确认（{now - job['submitted']:.1f}s）")
                    self.daily.add("replied")
                if job.get("after_image_generation"):
                    self.begin_image_generation(job["after_image_generation"])
                    return
                self.set_status("已发送并确认，继续监听", "listening")
                return
            if now - job.get("last_log", 0) >= 10:
                job["last_log"] = now
                self.log(f"等待 QQ 回显：群={group} 已等待={now - job['submitted']:.1f}s 界面可见消息={len(data['messages'])} 条")
        else:
            # 界面被别人切走时，主动切回目标群再确认，而不是干等到超时。
            self.log(f"确认期间界面在「{group or '未知'}」，切回「{job['group']}」")
            self.select(job["group"])
        self.expire_verification(now)

    def expire_verification(self, now):
        job = self.verifying
        if not job:
            return
        waited = now - job["submitted"]
        unseen = now - job.get("viewed", job["submitted"])
        if waited <= self.config.get("verify_max_seconds", 240) and unseen <= self.config.get("verify_seconds", 75):
            return
        self.verifying = None
        self.paused = True
        later = self.remember_uncertain(job, job.get("before", set()), "verify_timeout")
        self.live_finish("uncertain", "发送结果无法确认，已暂停且不会重发")
        self.log(f"发送结果无法确认，已暂停：群={job['group']} 已等待={waited:.1f}s 其中看不到目标群={unseen:.1f}s")
        self.native.call("pause", text="发送结果无法确认，已暂停；" + ("稍后自动检查，确认安全就恢复（不会重发）" if later else "不会自动重发"))
        self.set_status("发送结果无法确认，已停止处理；不会自动重发", "delivery_uncertain")

    # -- automatic resume after an uncertain send ------------------------------------------------------------------
    def remember_uncertain(self, job, before, reason):
        """Keep what is needed to check the chat later. True when an automatic check will follow."""
        self.daily.add("uncertain_pauses")
        delay = float(self.config.get("auto_resume_seconds", 30))
        if delay <= 0 or job.get("kind") == "image":
            self.uncertain = None
            return False
        now = time.monotonic()
        self.uncertain = {"group": job["group"], "text": job.get("text", ""), "before": set(before), "reason": reason,
                          "since": now, "next_check": now + delay, "attempts": 0}
        return True

    def check_auto_resume(self, now=None):
        """Paused because a send could not be confirmed: look at the chat and carry on when that is safe.
        Never resends: the reply was sent after all, or is dropped."""
        job = getattr(self, "uncertain", None)
        if not job or not self.paused or job.get("gave_up"):
            return
        now = time.monotonic() if now is None else now
        if now < job["next_check"]:
            return
        job["next_check"] = now + 10
        if now - job["since"] > 600:
            return self._give_up_resume(job, "10 分钟内没能看到那个聊天")
        resumes = [t for t in getattr(self, "auto_resumes", []) if now - t < 3600]
        if len(resumes) >= int(self.config.get("auto_resume_per_hour", 3)):
            return self._give_up_resume(job, "一小时内已经自动恢复过多次，可能有持续性问题")
        if self.user_typing(now):
            return
        data = parse_snapshot(self.native.call("snapshot"), self.config)
        if "error" in data:
            return
        if data.get("group") != job["group"] or not data.get("messages_ready", True):
            if job["attempts"] < 6:
                job["attempts"] += 1
                self.native.call("launch", app=self.config.get("qq_app", ""))
                self.native.call("select", group=job["group"], force=True)
            return
        draft = str(data.get("draft", "")).strip()
        if any(m.get("self") and m["id"] not in job["before"] and same_text(m.get("text", ""), job["text"]) for m in data["messages"]):
            outcome = "那条消息其实已经发出"
        elif not draft:
            outcome = "那条消息没有发出，输入栏是空的；不重发"
        elif same_text(draft, job["text"]):
            result = self.native.call("clear_draft", group=job["group"], text=job["text"])
            if result.get("ok") is not True:
                return
            outcome = "清掉了卡在输入栏的那条消息；不重发"
        else:
            return self._give_up_resume(job, "输入栏里有别的内容")
        self.uncertain = None
        self.auto_resumes = resumes + [now]
        self.daily.add("auto_resumes")
        self.log(f"自动恢复：{outcome}（群={job['group']}）")
        self.native.call("resume", text=outcome)

    def _give_up_resume(self, job, why):
        job["gave_up"] = True
        self.log(f"没有自动恢复：{why}；请检查 QQ 后手动继续")
        self.notify("需要你手动继续", f"{why}，请看一下 QQ 后点「开始」")

