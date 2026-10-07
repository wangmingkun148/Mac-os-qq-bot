"""Data the UI shows: live engine status plus the small JSON files the backend keeps under runtime/."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

PHASE_LABELS = {"offline": "后台无响应", "paused": "已暂停", "starting": "正在建立基线", "listening": "监听中", "waiting": "等待中",
                "thinking": "思考中", "sending": "发送中", "switching": "切换模型中", "attention": "需要注意"}
EMPTY_LIVE = {"version": 1, "updated_at": 0, "session_started": 0, "engine": {}, "stats": {"replied": 0, "silent": 0, "failed": 0},
              "waiting": [], "unvisited": [], "turns": [], "activity": [], "preview": None}


class FileCache:
    """JSON files re-read only when their modification time changes."""

    def __init__(self, base: Path):
        self.base = Path(base)
        self._entries: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def read(self, relative: str, default=None):
        path = self.base / relative
        try:
            stamp = path.stat().st_mtime
        except OSError:
            return default
        with self._lock:
            known = self._entries.get(relative)
            if known and known[0] == stamp:
                return known[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        with self._lock:
            self._entries[relative] = (stamp, data)
        return data


class StateReader:
    def __init__(self, app):
        self.app = app
        self.files = FileCache(app.base)

    def counters(self, status: dict) -> dict:
        return {
            "modelCalls": status.get("model_calls", 0), "verifiedReplies": status.get("verified_replies", 0),
            "inputTokens": status.get("input_tokens", 0), "outputTokens": status.get("output_tokens", 0),
            "lastInferenceSeconds": status.get("last_inference_seconds"), "model": status.get("model", ""),
            "archived": status.get("archived_messages", 0), "configWarnings": status.get("config_warnings", []),
            "configErrors": status.get("config_errors", []),
        }

    def chats(self, status: dict) -> list[dict]:
        details = status.get("conversations") or {}
        rows = [{"title": (d.get("title") or key), "kind": d.get("kind", "unknown")} for key, d in details.items()]
        return sorted(rows, key=lambda row: row["title"])

    def style_info(self) -> dict:
        config = self.app.config
        main = config.get("reply_style_group") or (config.get("groups") or [""])[0]
        data = self.files.read("runtime/style-profile.json", {}) or {}
        entry = (data.get("groups") or {}).get(main, {}) if isinstance(data, dict) else {}
        parts = [str(entry.get(key) or "").strip() for key in ("historical_summary", "summary")]
        parts = [p for p in parts if p]
        return {"chars": sum(len(p) for p in parts) + (2 if len(parts) > 1 else 0), "text": "\n".join(parts),
                "compressedAt": entry.get("compressed_at"), "versions": len(entry.get("versions") or [])}

    def preferences(self) -> dict:
        data = self.files.read("runtime/owner-preferences.json", {}) or {}
        return {"text": data.get("text", ""), "rounds": data.get("rounds", 0), "summarized": data.get("summarized", {}),
                "versions": len(data.get("versions") or []), "updatedAt": data.get("updated_at")}

    def ratings(self) -> dict:
        data = self.files.read("runtime/reply-feedback.json", {}) or {}
        return {key: value.get("rating") for key, value in data.items() if isinstance(value, dict) and value.get("rating")}

    def state(self) -> dict:
        app = self.app
        engine = app.engine
        if engine is not None:
            with engine.status_lock:
                status = dict(engine.status)
            live = engine.live.snapshot()
        else:
            status = self.files.read("runtime/status.json", {}) or {}
            live = self.files.read("runtime/live.json", None) or dict(EMPTY_LIVE)
        phase = app.phase()
        config = app.config
        ai = config.get("ai") or {}
        problem = status.get("message") if status.get("state") == "config_error" else None
        pet = config.get("pet") or {}
        return {
            "now": time.time(),
            "phase": phase, "phaseLabel": PHASE_LABELS.get(phase, phase), "paused": app.paused,
            "alive": app.backend_running, "statusText": app.status_text,
            "modelName": ai.get("model") or "未配置 AI", "providerName": ai.get("name") or "自定义 AI",
            "suffix": ai.get("suffix_enabled", True) is not False,
            "pet": {"enabled": pet.get("enabled", True), "scale": pet.get("scale", 4), "wander": pet.get("wander", True),
                    "bubble": pet.get("bubble", True)},
            "configError": problem, "setupProblem": None,
            "live": live, "counters": self.counters(status), "chats": self.chats(status),
            "daily": self.files.read("runtime/daily-stats.json", {}) or {},
            "ratings": self.ratings(), "styleInfo": self.style_info(), "preferences": self.preferences(),
            "feedbackEvery": config.get("feedback_summary_every", 20),
            "prefs": self.files.read("runtime/ui-prefs.json", {}) or {},
            "firstRun": app.first_run, "dryRun": app.dry_run,
        }
