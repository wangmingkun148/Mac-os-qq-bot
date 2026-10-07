"""A mock "QQ" for testing the Windows automation without touching a real account.

Serves tools/fake_qq/qq.html (a page that copies the DOM structure of QQ NT: conversation list, message list,
ProseMirror editor, send button, image context menu) plus a tiny API the tests use:

    POST /api/inject {"chat","sender","text","image"}   a message arrives
    GET  /api/inbox                                      (the page polls this)
    POST /api/sent                                       (the page reports what the user sent)
    GET  /api/sent                                       list of sent messages
    POST /v1/chat/completions                            a fake OpenAI-compatible AI that always answers "好的"
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = Path(__file__).with_name("qq.html")


class FakeQQ:
    def __init__(self):
        self.inbox = []
        self.sent = []
        self.logs = []
        self.lock = threading.Lock()
        self.ai_reply = "好的"
        self.ai_calls = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _send(self, status, body, kind="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", kind + "; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path.startswith("/api/inbox"):
                    with outer.lock:
                        events, outer.inbox = outer.inbox, []
                    return self._send(200, events)
                if self.path.startswith("/api/sent"):
                    with outer.lock:
                        return self._send(200, list(outer.sent))
                return self._send(200, PAGE.read_bytes(), "text/html")

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) or b"{}"
                if self.path.startswith("/api/log"):
                    outer.logs.append(raw.decode("utf-8", "replace"))
                    return self._send(200, {"ok": True})
                if self.path.startswith("/v1/chat/completions"):
                    outer.ai_calls += 1
                    answer = {"should_reply": True, "reply": outer.ai_reply, "reason": "fake"}
                    return self._send(200, {"choices": [{"message": {"content": json.dumps(answer, ensure_ascii=False)}}],
                                            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {}
                with outer.lock:
                    if self.path.startswith("/api/inject"):
                        outer.inbox.append(body)
                    elif self.path.startswith("/api/sent"):
                        outer.sent.append(body)
                return self._send(200, {"ok": True})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def inject(self, chat, sender, text="", image=False):
        with self.lock:
            self.inbox.append({"chat": chat, "sender": sender, "text": text, "image": image})

    def stop(self):
        self.server.shutdown()


if __name__ == "__main__":
    fake = FakeQQ()
    print(fake.url)
    threading.Event().wait()
