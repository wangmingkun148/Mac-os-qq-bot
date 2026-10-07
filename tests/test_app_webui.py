"""Tests for the app controller's config rules and the local web server's access control (no QQ, no engine)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from winapp.app import App, configuration_problem, normalize_config  # noqa: E402
from winapp.webui import WebUI  # noqa: E402

GOOD = {"groups": ["群"], "self_names": ["我"], "ai": {"base_url": "http://x/v1", "api_key": "sk-secret", "model": "m"}}


class ConfigRules(unittest.TestCase):
    def test_placeholders_and_missing_ai_block_start(self):
        self.assertIn("主群", configuration_problem({"groups": [], "self_names": ["我"], "ai": GOOD["ai"]}))
        self.assertIn("主群", configuration_problem({"groups": ["填写主群完整名称"], "self_names": ["我"], "ai": GOOD["ai"]}))
        self.assertIn("昵称", configuration_problem({"groups": ["群"], "self_names": [], "ai": GOOD["ai"]}))
        self.assertIn("AI", configuration_problem({"groups": ["群"], "self_names": ["我"], "ai": {"base_url": "x"}}))
        self.assertIsNone(configuration_problem(GOOD))

    def test_normalize_drops_placeholders_and_the_macos_key(self):
        config = normalize_config({"groups": ["填写主群完整名称", "群"], "self_names": ["填写本账号昵称"], "reply_mode": "regular"})
        self.assertEqual(config["groups"], ["群"])
        self.assertEqual(config["self_names"], [])
        self.assertNotIn("reply_mode", config)


class WebServer(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="qqbot-test-"))
        shutil.copytree(ROOT / "prompts", self.base / "prompts")
        for name in ("config.example.json", "bridge.py"):
            shutil.copy(ROOT / name, self.base / name)
        (self.base / "config.json").write_text(json.dumps(GOOD, ensure_ascii=False), encoding="utf-8")
        self.app = App(self.base)
        self.assertIsNone(self.app.prepare_project())
        self.applied = []
        self.app.restart_backend = lambda *args, **kwargs: None       # no engine in these tests
        self.web = WebUI(self.app, None)
        self.web.start()

    def tearDown(self):
        self.web.stop()
        shutil.rmtree(self.base, ignore_errors=True)

    def request(self, path, body=None, token=True, host=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.web.port}{path}", data=data, method="POST" if body is not None else "GET")
        if token:
            req.add_header("X-Token", self.web.token)
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, None

    def test_api_needs_the_token(self):
        self.assertEqual(self.request("/api/state", token=False)[0], 401)
        self.assertEqual(self.request("/api/config", token=False)[0], 401)
        self.assertEqual(self.request("/api/do", {"name": "quit"}, token=False)[0], 401)
        self.assertEqual(self.request("/api/state")[0], 200)

    def test_foreign_host_header_is_refused(self):
        self.assertEqual(self.request("/api/state", host="evil.example")[0], 403)

    def test_static_pages_are_served_without_a_token_but_not_outside_the_folder(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.web.port}/", timeout=5) as response:
            self.assertIn(b"<title>", response.read())
        self.assertEqual(self.request("/static/../app.py", token=False)[0], 404)

    def test_api_key_never_leaves_the_server(self):
        status, payload = self.request("/api/config")
        self.assertEqual(status, 200)
        self.assertEqual(payload["config"]["ai"]["api_key"], "")
        self.assertTrue(payload["hasSecret"]["ai.api_key"])
        self.assertNotIn("sk-secret", json.dumps(payload))

    def test_blank_secret_keeps_the_saved_key_and_a_new_one_replaces_it(self):
        config = self.request("/api/config")[1]["config"]
        config["ai"]["model"] = "other-model"
        self.assertEqual(self.request("/api/config", {"config": config, "restart": False})[1], {"problem": None})
        saved = json.loads((self.base / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["ai"]["model"], "other-model")
        self.assertEqual(saved["ai"]["api_key"], "sk-secret")
        config["ai"]["api_key"] = "sk-new"
        self.request("/api/config", {"config": config, "restart": False})
        self.assertEqual(json.loads((self.base / "config.json").read_text(encoding="utf-8"))["ai"]["api_key"], "sk-new")

    def test_invalid_config_is_rejected_with_a_message(self):
        config = self.request("/api/config")[1]["config"]
        config["groups"] = []
        problem = self.request("/api/config", {"config": config, "restart": False})[1]["problem"]
        self.assertIn("主群", problem)

    def test_people_notes_roundtrip(self):
        self.assertEqual(self.request("/api/people", {"people": [{"id": "1", "names": ["甲", " "], "call_as": "老甲", "about": "x", "notes": ""}]})[0], 200)
        people = self.request("/api/people")[1]["people"]
        self.assertEqual(people[0]["names"], ["甲"])
        self.assertEqual(people[0]["call_as"], "老甲")


if __name__ == "__main__":
    unittest.main()
