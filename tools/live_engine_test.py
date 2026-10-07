"""Drive the whole engine on the REAL QQ, inside one test group, with a fake AI.

    .venv\\Scripts\\python.exe -X utf8 tools\\live_engine_test.py <group>

The test group normally has only your own account, and the engine ignores your own messages. So the harness sends a
message that starts with "【测试】" and tells the engine to treat messages with that prefix as coming from someone else
(a monkeypatch in this process only). The engine then reads it, asks the fake AI, types the reply into QQ, sends it
and confirms it by reading it back, exactly as it would for a real member's message.

Only <group> is touched: the engine is configured with that single group and never switches chats.
Do not type or click while it runs (about a minute).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import comtypes  # noqa: E402

import engine as engine_module  # noqa: E402
import engine_delivery  # noqa: E402
from live_qq_test import read_me  # noqa: E402
from winapp import win32  # noqa: E402
from winapp.app import App  # noqa: E402
from winapp.qq import QQ  # noqa: E402

PREFIX = "【测试】"
REPLIES = []


class FakeAI(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        FakeAI.calls += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        reply = REPLIES.pop(0) if REPLIES else "收到，这是自动回复测试"
        body = json.dumps({"choices": [{"message": {"content": json.dumps({"should_reply": True, "reply": reply, "reason": "live test"}, ensure_ascii=False)}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def install_patch():
    for module in (engine_module, engine_delivery):
        original = module.parse_snapshot

        def patched(snapshot, config, _original=original):
            data = _original(snapshot, config)
            for message in data.get("messages", []):
                if message.get("self") and str(message.get("text", "")).startswith(PREFIX):
                    message["self"] = False
                    message["sender"] = "测试用户"
            return data

        module.parse_snapshot = patched


def wait_for(predicate, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


def main():
    group = sys.argv[1]
    win32.set_dpi_aware()
    comtypes.CoInitialize()
    probe = QQ(type("S", (), {"config": {}, "paused": False, "pending_send": False, "base": ".", "typing_seconds": lambda self: 99, "nativelog": lambda self, l: None})())
    me = read_me(probe)
    if not me:
        print("QQ not readable (no account nickname found)")
        return 1
    install_patch()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = Path(tempfile.mkdtemp(prefix="qqbot-liveengine-"))
    shutil.copytree(ROOT / "prompts", base / "prompts")
    for name in ("config.example.json", "bridge.py"):
        shutil.copy(ROOT / name, base / name)
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config.update({"groups": [group], "self_names": [me], "poll_seconds": 1, "merge_seconds": 1, "max_merge_seconds": 3, "cooldown_seconds": 0,
                   "typing_quiet_seconds": 1.0, "split_reply_min_chars": 0, "verify_seconds": 30, "reply_all_conversations": False})
    config["ai"].update({"name": "fake", "base_url": f"http://127.0.0.1:{server.server_port}/v1", "api_key": "test", "model": "fake", "suffix": "", "timeout_seconds": 20})
    (base / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    app = App(base)
    assert app.prepare_project() is None
    notices = []
    app.notify_sink = lambda title, body: notices.append((title, body))
    app.ensure_native()
    app.start_backend()
    time.sleep(1)
    app.toggle()
    ok = bool(wait_for(lambda: app.engine and app.engine.status.get("baseline_groups"), 30))
    print(("PASS" if ok else "FAIL"), "engine built the baseline from the real test group |", app.status_text.replace(group, "<group>"), flush=True)
    results = [ok]
    if ok:
        for label, trigger, reply in (("plain reply", f"{PREFIX}你好，请回复一下 {time.strftime('%H:%M:%S')}", "收到，这是自动回复测试"),
                                      ("reply that starts with an @mention", f"{PREFIX}再来一条 {time.strftime('%H:%M:%S')}", f"@{me} 收到，带 @ 的回复")):
            REPLIES.append(reply)
            replies_before = app.engine.status.get("verified_replies", 0)
            result = app.native.call("send", group=group, text=trigger)
            print(f"   trigger sent: {result}", flush=True)
            confirmed = wait_for(lambda: app.engine.status.get("verified_replies", 0) > replies_before, 40)
            good = bool(confirmed)
            print(("PASS" if good else "FAIL"), f"{label}: engine replied and confirmed the send |", app.status_text.replace(group, "<group>").replace(me, "<me>"), flush=True)
            results.append(good)
            time.sleep(2)
    print("pauses/uncertain notices:", [t for t, _ in notices if "暂停" in t or "未确认" in t or "不确定" in t])
    app.toggle()                                            # pause
    time.sleep(1)
    log = base / "runtime" / "bridge.log"
    if log.exists():
        print("--- bridge.log (tail) ---")
        for line in log.read_text(encoding="utf-8").splitlines()[-14:]:
            print("  ", line.replace(group, "<group>").replace(me, "<me>")[:170])
    native_log = base / "runtime" / "native.log"
    if native_log.exists():
        print("--- native.log (tail) ---")
        for line in native_log.read_text(encoding="utf-8").splitlines()[-10:]:
            print("  ", line[:170])
    app.shutdown()
    shutil.rmtree(base, ignore_errors=True)
    print(f"{sum(results)}/{len(results)} checks passed; fake AI calls: {FakeAI.calls}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
