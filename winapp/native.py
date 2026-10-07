"""The Windows implementation of the backend's "native" interface.

``engine.Engine`` talks to a ``native`` object: an ``events`` queue it reads and a ``call(op, **kwargs)`` method it
uses to read and drive QQ. On macOS that object spoke JSON over a pipe to the Swift app; here it runs in-process.

UI Automation and input injection run on one dedicated worker thread (COM apartment), one operation at a time,
exactly like the macOS main-thread handler did.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from pathlib import Path

LOCAL_OPS = {"typing", "status", "pause", "notify", "resume"}


class WinNative:
    # How long the engine waits for an answer. Sending an image takes ~15 s of timed steps by design.
    TIMEOUTS = {"send_image": 60, "send": 25, "capture_image": 20, "capture_latest_image": 20, "select": 15,
                "snapshot": 20}

    def __init__(self, base: Path, config: dict, hooks=None):
        self.base = Path(base)
        self.config = config
        self.hooks = hooks                  # optional: on_status(text), on_pause(text), on_notify(title, text), on_resume(text)
        self.events = queue.Queue()
        self.paused = True
        self.pending_send = False
        self.dry_run = False
        self.jobs: queue.Queue = queue.Queue()
        self.qq = None
        self._log_lock = threading.Lock()
        self.typing = None
        self.worker = threading.Thread(target=self._work, name="qq-automation", daemon=True)
        self.ready = threading.Event()
        self.worker.start()
        self.ready.wait(10)

    # ------------------------------------------------------------------ shell services used by qq.QQ
    def typing_seconds(self) -> float:
        return self.typing.seconds_since_typing() if self.typing else float("inf")

    def nativelog(self, line: str):
        path = self.base / "runtime" / "native.log"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._log_lock:
                if path.exists() and path.stat().st_size > 512_000:
                    path.unlink()
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{stamp} {line}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ the engine-facing interface
    def emit(self, event: dict):
        self.events.put(event)

    def call(self, op: str, **kwargs):
        if op in LOCAL_OPS:
            return self._local(op, kwargs)
        reply: queue.Queue = queue.Queue(1)
        self.jobs.put((op, kwargs, reply))
        try:
            return reply.get(timeout=self.TIMEOUTS.get(op, 12))
        except queue.Empty:
            if op in ("send", "send_image"):
                return {"error": "native_timeout"}      # the keystrokes may well have gone out: never resend blindly
            raise

    def shutdown(self):
        self.events.put({"event": "shutdown"})

    def close(self):
        self.jobs.put((None, None, None))

    # ------------------------------------------------------------------ operations that need no automation
    def _local(self, op, kw):
        hooks = self.hooks
        if op == "typing":
            seconds = self.typing_seconds()
            quiet = self.config.get("typing_quiet_seconds", 3)
            return {"typing": seconds < float(quiet if isinstance(quiet, (int, float)) else 3), "seconds": min(seconds, 1e6)}
        if op == "status":
            if hooks:
                hooks.on_status(kw.get("text", ""))
        elif op == "pause":
            self.paused = True
            if hooks:
                hooks.on_pause(kw.get("text", "已暂停"))
        elif op == "notify":
            if hooks:
                hooks.on_notify(kw.get("title", "QQ Bot"), kw.get("text", ""))
        elif op == "resume":
            if hooks:
                hooks.on_resume(kw.get("text", ""))
        return {"ok": True}

    # ------------------------------------------------------------------ automation worker
    def _work(self):
        import comtypes
        from . import win32
        from .qq import QQ
        comtypes.CoInitialize()
        try:
            self.typing = win32.TypingWatcher()
            self.typing.start()
            self.qq = QQ(self)
        finally:
            self.ready.set()
        while True:
            op, kwargs, reply = self.jobs.get()
            if op is None:
                break
            try:
                result = self._dispatch(op, kwargs)
            except Exception as exc:                  # never let the worker die: report and keep going
                self.nativelog(f"{op} raised {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
                self.pending_send = False
                result = {"error": f"native_exception: {type(exc).__name__}"}
            reply.put(result)
        comtypes.CoUninitialize()

    def _dispatch(self, op, kw):
        qq = self.qq
        if op == "snapshot":
            return qq.snapshot()
        if self.dry_run:                                  # read-only mode: look, never touch QQ
            self.nativelog(f"dry run: {op} {kw if op != 'send' else {'group': kw.get('group'), 'chars': len(kw.get('text', ''))}}")
            return {"ok": True} if op in ("wake", "launch") else {"error": "dry_run"}
        if op == "wake":
            return qq.wake()
        if op == "launch":
            return qq.launch(kw.get("app", ""))
        if op == "select":
            return qq.select(kw.get("group", ""), force=bool(kw.get("force", False)))
        if op == "capture_image":
            return qq.capture_image(kw.get("group", ""), message_id=kw.get("message_id", ""))
        if op == "capture_latest_image":
            return qq.capture_image(kw.get("group", ""), latest=True, exclude=kw.get("exclude_ids", []))
        if op == "clear_draft":
            return qq.clear_draft(kw.get("group", ""), kw.get("text", ""))
        if op == "send":
            return qq.send(kw.get("group", ""), kw.get("text", ""))
        if op == "send_image":
            return qq.send_image(kw.get("group", ""), kw.get("text", ""), kw.get("path", ""))
        return {"error": "unknown_operation"}
