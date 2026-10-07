"""Bounded browser tasks: the AI picks one step at a time; a dedicated Chrome (Playwright) worker or Jina Reader does it."""
import json
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from browser_worker import read_page
from temporal_relevance import outdated_for_current_claim, today


def browser_request(fresh, recent):
    for message in reversed(fresh):
        text = message.get("text", "")
        if message.get("self") or message.get("bot"):
            continue
        urls = re.findall(r"https?://[^\s<>\"，。！）]+", text)
        explicit = bool(re.search(r"打开|浏览|播放|暂停|阅读|读一下|看看.{0,6}(?:链接|网页|视频)|总结.{0,6}(?:链接|网页|视频)", text))
        if urls:
            return {"request": text[:2000], "url": urls[-1].rstrip(").,!?"), "sender": message.get("sender", ""),
                    "automatic": not explicit, "playback_requested": bool(re.search(r"播放|继续播放", text))}
        if not explicit:
            continue
        if not urls and re.search(r"这个|刚才|链接|网页|视频|暂停|继续播放", text):
            for previous in reversed(recent[-12:]):
                urls = re.findall(r"https?://[^\s<>\"，。！）]+", previous.get("text", ""))
                if urls:
                    break
        if urls:
            return {"request": text[:2000], "url": urls[-1].rstrip(").,!?"), "sender": message.get("sender", ""),
                    "automatic": False, "playback_requested": bool(re.search(r"播放|继续播放", text))}
    return None


class BrowserAgent:
    def __init__(self, base, config):
        self.base, self.config = base, config
        self.process = None
        self.responses = queue.Queue()
        self.cancelled = threading.Event()

    def close(self):
        self.cancelled.set()
        process, self.process = self.process, None
        if process and process.poll() is None:
            process.terminate()

    def call(self, action):
        if action.get("action") == "reader":
            try:
                return read_page(action.get("url", ""))
            except Exception as exc:
                return {"error": str(exc)[:500]}
        if not self.process or self.process.poll() is not None:
            c = self.config.get("browser", {})
            python = c.get("python") or sys.executable
            profile = self.base / "runtime/browser-profile"
            self.responses = queue.Queue()
            with (self.base / "runtime/browser-worker.log").open("a", encoding="utf-8") as errors:
                self.process = subprocess.Popen([python, "-u", str(self.base / "browser_worker.py"), str(profile)],
                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, text=True)
            process, responses = self.process, self.responses
            def read():
                for line in process.stdout:
                    try:
                        responses.put(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                responses.put({"error": "浏览器进程已退出，请检查 browser-worker.log"})
            threading.Thread(target=read, daemon=True).start()
        self.process.stdin.write(json.dumps(action) + "\n")
        self.process.stdin.flush()
        try:
            return self.responses.get(timeout=140 if action.get("action") == "video_frames" else 45)
        except queue.Empty:
            self.close()
            return {"error": "浏览器动作超时，任务已停止"}

    def run(self, model, request):
        paths = []
        try:
            return self._run_task(model, request, paths)
        finally:
            for path in paths:
                Path(path).unlink(missing_ok=True)

    def _run_task(self, model, request, paths):
        self.cancelled.clear()
        started = time.monotonic()
        observation = self.call({"action": "open", "url": request["url"]})
        first = "open"
        if "浏览器进程已退出" in str(observation.get("error", "")):
            # Chrome / Playwright is not available here: read the page's text through Jina Reader instead
            observation, first = self.call({"action": "reader", "url": request["url"]}), "reader"
        page_dates = observation.get("dates", {})
        history = [{"action": first, "url": request["url"], "error": observation.get("error")}]
        pending_images = []
        sampled_urls = set()
        visual_notes = []
        usage = {"input_tokens": 0, "output_tokens": 0}
        selected_model = self.config.get("ai", {}).get("model", "")
        selected_effort = self.config.get("ai", {}).get("reasoning_effort") or ""
        allowed_urls = {request["url"]}
        allowed_urls.update(link["url"] for link in observation.get("links", []) if link.get("url"))
        if observation.get("url"):
            allowed_urls.add(observation["url"])
        calls = 0
        for step in range(6):
            if self.cancelled.is_set():
                raise RuntimeError("浏览任务已取消")
            published = page_dates.get("published") or page_dates.get("modified", "")
            outdated = outdated_for_current_claim(request.get("request", ""), published,
                                                  observation.get("title", ""), include_title_announcements=False)
            payload = {"task": request, "step": step + 1, "max_steps": 6, "actions": history,
                       "current_date": today(), "source_published": published,
                       "source_outdated_for_current_question": outdated,
                       "visual_notes": visual_notes, "observation": observation}
            action, used, _, _ = model.run_task("browser", payload, images=[(str(i), path) for i, path in enumerate(pending_images)])
            if pending_images and action.get("visual_summary"):
                visual_notes.append(action["visual_summary"][:2000])
            pending_images = []
            calls += 1
            if self.cancelled.is_set():
                raise RuntimeError("浏览任务已取消")
            for key in usage:
                usage[key] += used.get(key, 0)
            if action.get("action") == "finish":
                reply = str(action.get("reply", "")).strip().replace("\n", " ")[:160]
                if outdated and reply and not re.search(r"旧|当时|往年|过期|已结束|不能确认|无法确认|不确定|不是现", reply):
                    reply = f"这页是较早的资料（{published[:10]}），不能据此确认现在的活动情况。"
                break
            if step == 5:
                reply = "" if request.get("automatic") else "这次浏览任务达到步数上限，还没完成。"
                break
            if action.get("action") == "play" and not request.get("playback_requested"):
                observation = {"error": "群友没有明确要求播放，已禁止自动播放"}
            elif action.get("action") in ("open", "reader") and action.get("url") not in allowed_urls:
                observation = {"error": "只能打开群友提供或页面实际观察到的链接"}
            elif action.get("action") == "video_frames":
                info = observation.get("video", {})
                current_url = observation.get("url")
                if action.get("worth_watching") is not True:
                    observation = {**observation, "error": "未判断值得继续看，不进行视觉调用"}
                elif info.get("subtitles_status") == "available" and action.get("needs_visual") is not True:
                    observation = {**observation, "error": "已有字幕且无需画面，不抽帧"}
                elif not info.get("present") or current_url in sampled_urls:
                    observation = {**observation, "error": "未检测到视频或本任务已经抽取过该视频"}
                else:
                    sampled_urls.add(current_url)
                    action["frame_count"] = max(5, min(20, int(action.get("frame_count", 8))))
                    observation = self.call(action)
                    for frame in observation.get("frames", []):
                        path = Path(frame["path"]).resolve()
                        folder = (self.base / "runtime/video-frames").resolve()
                        if path.parent == folder and path.is_file():
                            paths.append(str(path))
                            pending_images.append(str(path))
                    observation["attached_frame_count"] = len(pending_images)
            else:
                observation = self.call(action)
                if action.get("action") in ("open", "reader"):
                    page_dates = observation.get("dates", {})
                elif observation.get("dates"):
                    page_dates = observation["dates"]
                allowed_urls.update(link["url"] for link in observation.get("links", []) if link.get("url"))
                if observation.get("url"):
                    allowed_urls.add(observation["url"])
            history.append({"action": action.get("action"), "url": action.get("url"), "error": observation.get("error")})
            with (self.base / "runtime/browser.log").open("a", encoding="utf-8") as log:
                log.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "step": step + 1,
                       **history[-1], "media": observation.get("media"), "subtitles_status": observation.get("video", {}).get("subtitles_status"),
                       "worth_watching": action.get("worth_watching"), "needs_visual": action.get("needs_visual"),
                       "frames": len(pending_images), "model": selected_model, "effort": selected_effort}, ensure_ascii=False) + "\n")
        if not reply and not request.get("automatic"):
            reply = "浏览任务结束，未得到可用结果。"
        return {"kind": "browser", "should_reply": bool(reply), "reply": reply,
                "reason": "浏览器任务", "usage": usage, "seconds": round(time.monotonic() - started, 2),
                "browser_calls": calls, "actions": history, "video_frames": len(paths),
                "model": selected_model, "reasoning_effort": selected_effort}
