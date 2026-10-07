"""File helpers that behave the same on macOS, Linux and Windows."""
from __future__ import annotations
import os
import time


def replace(source, target, attempts: int = 25, delay: float = 0.04):
    """``os.replace`` that waits out the short sharing violations Windows reports while another process (the UI,
    an indexer, antivirus) still has the target open."""
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1 or os.name != "nt":
                raise
            time.sleep(delay)


def read_json_text(path) -> str:
    """Text of a JSON file written by this app or by hand (UTF-8, with or without a byte-order mark)."""
    with open(path, encoding="utf-8-sig") as handle:
        return handle.read()
