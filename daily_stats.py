"""Per-day counters for the "今日简报" panel, kept in runtime/daily-stats.json (survives restarts, last 30 days)."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
import fsutil

KEEP_DAYS = 30


class DailyStats:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.days = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.days, dict):
                self.days = {}
        except (OSError, json.JSONDecodeError):
            self.days = {}

    def add(self, key: str, amount: float = 1, day: str | None = None):
        day = day or time.strftime("%Y-%m-%d")
        with self.lock:
            counters = self.days.setdefault(day, {})
            counters[key] = round(counters.get(key, 0) + amount, 2)
            for old in sorted(self.days)[:-KEEP_DAYS]:
                del self.days[old]
            data = json.dumps(self.days, ensure_ascii=False, indent=1, sort_keys=True)
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            os.chmod(tmp, 0o600)
            fsutil.replace(tmp, self.path)
        except OSError:
            pass

    def today(self) -> dict:
        return dict(self.days.get(time.strftime("%Y-%m-%d"), {}))
