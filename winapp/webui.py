"""The local web server behind the UI windows (tray popover, status window, settings).

It listens on 127.0.0.1 only and every API call must carry the per-run token that the launcher puts in the page
URL, so other programs and web pages cannot read the config (which contains API keys) or press buttons."""
from __future__ import annotations

import copy
import json
import mimetypes
import os
import secrets
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import fsutil

from .state import StateReader

SECRET_PATHS = ("ai.api_key", "image_generation.api_key")
OPENABLE = {"log": "runtime/bridge.log", "backend_log": "runtime/backend.log", "native_log": "runtime/native.log",
            "config": "config.json", "folder": ""}


def ui_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "winapp" / "ui"
    return Path(__file__).resolve().parent / "ui"


def get_path(data: dict, dotted: str):
    current = data
    for key in dotted.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def set_path(data: dict, dotted: str, value):
    keys = dotted.split(".")
    current = data
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = current[key] = {}
        current = child
    current[keys[-1]] = value


class WebUI:
    def __init__(self, app, shell=None):
        self.app = app
        self.shell = shell
        self.token = secrets.token_urlsafe(24)
        self.reader = StateReader(app)
        self.directory = ui_directory()
        self.people_lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "QQBridgeUI"

            def log_message(self, *args):
                pass

            def _host_ok(self):
                host = (self.headers.get("Host") or "").lower()
                return host in (f"127.0.0.1:{outer.port}", f"localhost:{outer.port}")

            def _send(self, status, body: bytes, content_type="application/json; charset=utf-8", extra=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for key, value in (extra or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, payload, status=200):
                self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

            def _authorized(self):
                return secrets.compare_digest(self.headers.get("X-Token", ""), outer.token)

            def do_GET(self):
                if not self._host_ok():
                    return self._send(403, b"forbidden", "text/plain")
                path = urlsplit(self.path).path
                if path.startswith("/api/"):
                    if not self._authorized():
                        return self._json({"error": "unauthorized"}, 401)
                    return self._api("GET", path, None)
                return self._static(path)

            def do_POST(self):
                if not self._host_ok() or not self._authorized():
                    return self._json({"error": "unauthorized"}, 401)
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    return self._json({"error": "bad json"}, 400)
                return self._api("POST", urlsplit(self.path).path, body)

            def _static(self, path):
                name = "index.html" if path in ("/", "") else path.lstrip("/")
                if name.startswith("static/"):
                    name = name[len("static/"):]
                target = (outer.directory / name).resolve()
                if outer.directory.resolve() not in target.parents or not target.is_file():
                    return self._send(404, b"not found", "text/plain")
                kind = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if target.suffix == ".otf":
                    kind = "font/otf"
                self._send(200, target.read_bytes(), kind + ("; charset=utf-8" if kind.startswith("text/") or kind.endswith("javascript") else ""))

            def _api(self, method, path, body):
                try:
                    result = outer.handle(method, path, body)
                except Exception as exc:                       # the UI must never take the app down
                    return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                if result is None:
                    return self._json({"error": "not found"}, 404)
                return self._json(result)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, name="web-ui", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def url(self, view: str) -> str:
        return f"http://127.0.0.1:{self.port}/#{view}?t={self.token}"

    # ------------------------------------------------------------------ API
    def handle(self, method, path, body):
        app = self.app
        if method == "GET":
            if path == "/api/state":
                state = self.reader.state()
                windows = getattr(self.shell, "windows", None)
                state["ui"] = {"pinned": windows.pinned if windows else True, "command": windows.command if windows else {}}
                return state
            if path == "/api/config":
                return self.public_config()
            if path == "/api/people":
                return {"people": self.read_people()}
            if path == "/api/diagnostics":
                return app.diagnostics()
            return None
        if path == "/api/config":
            return self.save_config(body)
        if path == "/api/people":
            return self.write_people(body.get("people") or [])
        if path == "/api/do":
            return self.do(body)
        return None

    def public_config(self) -> dict:
        self.app.load_config()
        config = copy.deepcopy(self.app.config)
        flags = {}
        for dotted in SECRET_PATHS:
            flags[dotted] = bool(str(get_path(config, dotted) or "").strip())
            if get_path(config, dotted) is not None:
                set_path(config, dotted, "")
        return {"config": config, "hasSecret": flags}

    def save_config(self, body) -> dict:
        new = copy.deepcopy(body.get("config") or {})
        self.app.load_config()
        for dotted in SECRET_PATHS:                       # an empty secret field means "keep what is saved"
            if not str(get_path(new, dotted) or "").strip():
                set_path(new, dotted, get_path(self.app.config, dotted) or "")
        problem = self.app.apply_config(new, restart=bool(body.get("restart")))
        return {"problem": problem}

    def people_path(self) -> Path:
        return self.app.base / "runtime" / "people.json"

    def read_people(self) -> list:
        try:
            data = json.loads(self.people_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        people = data.get("people") if isinstance(data, dict) else []
        return people if isinstance(people, list) else []

    def write_people(self, people: list) -> dict:
        clean = []
        for person in people:
            if not isinstance(person, dict):
                continue
            entry = {"id": str(person.get("id") or uuid.uuid4()), "names": [str(n) for n in person.get("names", []) if str(n).strip()],
                     "call_as": str(person.get("call_as", "")), "about": str(person.get("about", "")), "notes": str(person.get("notes", ""))}
            if person.get("drafted"):
                entry["drafted"] = True
            clean.append(entry)
        path = self.people_path()
        tmp = path.with_suffix(".tmp")
        with self.people_lock:
            tmp.write_text(json.dumps({"version": 1, "people": clean}, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            fsutil.replace(tmp, path)
        return {"ok": True, "savedAt": time.time()}

    def do(self, body) -> dict:
        app = self.app
        name = body.get("name")
        if name == "toggle":
            app.toggle()
            if app.show_settings_requested:
                app.show_settings_requested = False
                if self.shell:
                    self.shell.open_window("settings", "general")
        elif name == "suffix":
            app.set_suffix(bool(body.get("on")))
        elif name == "pet":
            app.set_pet_enabled(bool(body.get("on")))
        elif name == "proactive":
            app.request_proactive()
        elif name == "choose_topic":
            app.choose_topic(int(body.get("index", -1)))
        elif name == "rate":
            app.rate_reply(body.get("turn") or {}, body.get("rating"))
        elif name == "revert_style":
            app.revert_style_compression()
        elif name == "revert_feedback":
            app.revert_feedback_round()
        elif name == "restart_backend":
            app.restart_backend("正在重启回复服务")
        elif name == "open":
            target = OPENABLE.get(body.get("target", ""))
            if target is None:
                return {"ok": False}
            path = app.base / target if target else app.base
            if path.exists():
                os.startfile(str(path))  # noqa: S606
        elif name == "window" and self.shell:
            self.shell.open_window(body.get("kind", "live"), body.get("section"))
        elif name == "pin" and self.shell:
            self.shell.set_pinned(bool(body.get("on")))
        elif name == "set_pref":
            key, value = str(body.get("key", "")), body.get("value")
            if key in ("appearance",) and value in ("system", "light", "dark"):
                path = app.base / "runtime" / "ui-prefs.json"
                try:
                    prefs = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    prefs = {}
                prefs[key] = value
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
                fsutil.replace(tmp, path)
        elif name == "test_notification":
            app.notify("QQ 自动回复", "这是一条测试通知", force=True)
        elif name == "quit" and self.shell:
            threading.Thread(target=self.shell.quit, daemon=True).start()
        else:
            return {"ok": False, "error": "unknown action"}
        return {"ok": True}
