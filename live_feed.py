"""Live activity feed for the status window.

The engine records one *turn* per batch of messages it handles (judge -> generate -> send -> confirm)
and a list of messages still waiting to be merged. The whole snapshot is written atomically to
``runtime/live.json`` so the native UI can poll it without talking to the engine.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
import fsutil

TURN_LIMIT = 40
ACTIVITY_LIMIT = 60
TEXT_LIMIT = 240
THOUGHT_LIMIT = 1800


def _clip(value, limit):
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def brief_message(message):
    return {"id": str(message.get("id", "")), "sender": _clip(message.get("sender", ""), 40),
            "text": _clip(message.get("text", ""), TEXT_LIMIT), "image": bool(message.get("has_image"))}


class LiveFeed:
    def __init__(self, path: Path, limit: int = TURN_LIMIT):
        self.path = Path(path)
        self.limit = limit
        self.lock = threading.RLock()
        self.turns: list[dict] = []
        self.waiting_list: list[dict] = []
        self.unvisited_list: list[dict] = []
        self.activity: list[dict] = []
        self.preview: dict | None = None
        self.engine: dict = {}
        self.serial = 0
        self.started = time.time()
        self.dirty = True

    # -- recording -------------------------------------------------------------------------
    def set_engine(self, **fields):
        with self.lock:
            changed = {key: value for key, value in fields.items() if self.engine.get(key) != value}
            if not changed:
                return
            if "state" in changed or "message" in changed:
                changed["since"] = time.time()
            self.engine.update(changed)
            self.dirty = True

    def set_waiting(self, groups: dict[str, tuple[str, list[dict]]]):
        """groups maps conversation key -> (title, pending messages)."""
        with self.lock:
            previous = {item["group"]: item for item in self.waiting_list}
            current = []
            for group, (title, messages) in groups.items():
                if not messages:
                    continue
                since = previous.get(group, {}).get("since", time.time())
                current.append({"group": group, "title": _clip(title, 60), "since": since,
                                "messages": [brief_message(m) for m in messages[-6:]], "count": len(messages)})
            if [(w["group"], w["count"]) for w in current] != [(w["group"], w["count"]) for w in self.waiting_list]:
                self.dirty = True
            self.waiting_list = current

    def set_unvisited(self, chats: list[dict]):
        """Chats whose sidebar preview changed but which the bot has not opened yet: [{group, title, since, count}]."""
        with self.lock:
            chats = [{"group": c["group"], "title": _clip(c["title"], 60), "since": c["since"], "count": c["count"]} for c in chats]
            if [(c["group"], c["count"]) for c in chats] != [(c["group"], c["count"]) for c in self.unvisited_list]:
                self.dirty = True
            self.unvisited_list = chats

    def set_preview(self, preview: dict | None):
        """The openings waiting for the owner to pick one (a manual 主动发起话题), or None when nothing is pending."""
        with self.lock:
            if preview is not None:
                preview = {**preview, "options": [{**option, "text": _clip(option.get("text"), TEXT_LIMIT * 2)} for option in preview.get("options", [])]}
            if preview != self.preview:
                self.preview, self.dirty = preview, True

    def begin(self, group: str, title: str, kind: str, messages: list[dict]) -> str:
        with self.lock:
            self.serial += 1
            turn_id = f"t{int(self.started)}-{self.serial}"
            now = time.time()
            self.turns.append({
                "id": turn_id, "group": group, "title": _clip(title or group, 60), "kind": kind,
                "started": now, "stage": "judging", "stage_since": now, "outcome": None, "ended": None,
                "messages": [brief_message(m) for m in messages[-8:]], "message_count": len(messages),
                "decision": None, "reply": None, "thoughts": [], "timeline": [], "tokens": None,
            })
            self.turns = self.turns[-self.limit:]
            self._event(turn_id, "judging", "开始处理")
            self.dirty = True
            return turn_id

    def _turn(self, turn_id):
        return next((turn for turn in reversed(self.turns) if turn["id"] == turn_id), None)

    def _event(self, turn_id, stage, text):
        turn = self._turn(turn_id)
        if turn is not None:
            turn["timeline"].append({"t": time.time(), "stage": stage, "text": _clip(text, 200)})
            turn["timeline"] = turn["timeline"][-24:]

    def step(self, turn_id: str | None, stage: str, text: str = ""):
        with self.lock:
            turn = self._turn(turn_id) if turn_id else None
            if turn is None or turn["outcome"]:
                return
            if turn["stage"] != stage:
                turn["stage"], turn["stage_since"] = stage, time.time()
            if text:
                self._event(turn_id, stage, text)
            self.dirty = True

    def update(self, turn_id: str | None, **fields):
        """Merge result details; ``thoughts`` are appended, other dict fields are merged."""
        with self.lock:
            turn = self._turn(turn_id) if turn_id else None
            if turn is None:
                return
            for key, value in fields.items():
                if key == "thoughts":
                    for item in value or []:
                        text = str(item or "").strip()[:THOUGHT_LIMIT]
                        if text and text not in turn["thoughts"]:
                            turn["thoughts"].append(text)
                    turn["thoughts"] = turn["thoughts"][-6:]
                elif key in ("decision", "reply") and isinstance(value, dict):
                    merged = {**(turn.get(key) or {}), **{k: v for k, v in value.items() if v is not None}}
                    for text_key in ("reason", "text"):
                        if text_key in merged:
                            merged[text_key] = _clip(merged[text_key], 400)
                    turn[key] = merged
                else:
                    turn[key] = value
            self.dirty = True

    def finish(self, turn_id: str | None, outcome: str, text: str = ""):
        with self.lock:
            turn = self._turn(turn_id) if turn_id else None
            if turn is None or turn["outcome"]:
                return
            turn["outcome"], turn["ended"] = outcome, time.time()
            turn["stage"], turn["stage_since"] = "done", turn["ended"]
            self._event(turn_id, "done", text or {"replied": "已发送并确认", "silent": "本轮不接话"}.get(outcome, outcome))
            self.dirty = True

    def note(self, text: str):
        with self.lock:
            self.activity.append({"t": time.time(), "text": _clip(text, 220)})
            self.activity = self.activity[-ACTIVITY_LIMIT:]
            self.dirty = True

    # -- output ----------------------------------------------------------------------------
    def snapshot(self) -> dict:
        with self.lock:
            counts = {"replied": 0, "silent": 0, "failed": 0}
            for turn in self.turns:
                if turn["outcome"] == "replied":
                    counts["replied"] += 1
                elif turn["outcome"] == "silent":
                    counts["silent"] += 1
                elif turn["outcome"] in ("failed", "uncertain", "abandoned"):
                    counts["failed"] += 1
            return {"version": 1, "updated_at": time.time(), "session_started": self.started,
                    "engine": dict(self.engine), "stats": counts, "waiting": list(self.waiting_list), "unvisited": list(self.unvisited_list),
                    "turns": list(reversed(self.turns)), "activity": list(reversed(self.activity)), "preview": self.preview}

    def flush(self, force: bool = False):
        with self.lock:
            if not (self.dirty or force):
                return
            self.dirty = False
            data = json.dumps(self.snapshot(), ensure_ascii=False)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            os.chmod(tmp, 0o600)
            fsutil.replace(tmp, self.path)
        except OSError:
            pass
