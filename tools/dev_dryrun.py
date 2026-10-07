"""Developer harness: run the whole backend against the live QQ window in READ-ONLY mode.

* a throw-away project folder is built under a temp directory (your real config.json is never touched);
* the chat that is open in QQ becomes the "main group", the logged-in nickname comes from the top bar;
* a tiny local server pretends to be the AI provider, so no real API key or network is needed;
* QQ is only read: select/send/capture are refused by the dry-run switch.

    .venv\\Scripts\\python.exe -X utf8 tools\\dev_dryrun.py [seconds]
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

import comtypes  # noqa: E402

from winapp import tree as T  # noqa: E402
from winapp import uia, win32  # noqa: E402


class FakeAI(BaseHTTPRequestHandler):
    calls = 0

    def do_POST(self):
        FakeAI.calls += 1
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        answer = {"should_reply": True, "reply": "dry-run reply", "reason": "dry run"}
        body = json.dumps({"choices": [{"message": {"content": json.dumps(answer)}}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def live_identity():
    comtypes.CoInitialize()
    windows = [w for w in uia.top_level_windows() if w["visible"] and w["title"] == "QQ"]
    window = max(windows, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))
    tree = T.annotate(uia.dump_tree(uia.element_from_handle(window["hwnd"], uia.DUMP_PROPS)))
    me = next((n["desc"][:-3] for n in T.nodes(tree) if n.get("role") == "AXButton" and n.get("desc", "").endswith("的头像")), "")
    return T.current_title(tree), me


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25
    title, me = live_identity()
    if not title or not me:
        print("open a chat in QQ first")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = Path(tempfile.mkdtemp(prefix="qqbot-dev-"))
    for name in ("prompts",):
        shutil.copytree(ROOT / name, base / name)
    for name in ("config.example.json", "bridge.py"):
        shutil.copy(ROOT / name, base / name)
    config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
    config.update({"groups": [title], "self_names": [me], "poll_seconds": 1, "merge_seconds": 1, "cooldown_seconds": 0})
    config["ai"].update({"name": "fake", "base_url": f"http://127.0.0.1:{server.server_port}/v1", "api_key": "test", "model": "fake"})
    (base / "config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

    from winapp.app import App
    win32.set_dpi_aware()
    app = App(base, dry_run=True)
    assert app.prepare_project() is None
    seen = []

    def mask(text):
        return text.replace(title, "<chat>").replace(me, "<me>")

    def changed():
        if not seen or seen[-1] != app.status_text:
            seen.append(app.status_text)
            print(f"  [{time.strftime('%H:%M:%S')}] {mask(app.status_text)}", flush=True)

    app.on_state_change = changed
    app.ensure_native()
    app.start_backend()
    time.sleep(1.0)
    app.toggle()
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.5)
    engine = app.engine
    if engine is not None:
        print("engine state:", engine.status.get("state"), "| archived messages:", engine.status.get("archived_messages"),
              "| baseline groups:", len(engine.status.get("baseline_groups", [])), "| model calls:", engine.status.get("model_calls"))
        print("conversations seen:", len(engine.conversation_details), "| fake AI calls:", FakeAI.calls)
    else:
        print("engine is not running")
    app.shutdown()
    log = base / "runtime" / "bridge.log"
    if log.exists():
        lines = log.read_text(encoding="utf-8").splitlines()
        print(f"bridge.log: {len(lines)} lines")
        for line in lines[-12:]:
            print("   ", mask(line)[:200])
    native_log = base / "runtime" / "native.log"
    if native_log.exists():
        print("native.log:", len(native_log.read_text(encoding="utf-8").splitlines()), "lines")
    backend_log = base / "runtime" / "backend.log"
    if backend_log.exists():
        print("backend.log (crash trace):")
        print(backend_log.read_text(encoding="utf-8")[-1500:])
    shutil.rmtree(base, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
