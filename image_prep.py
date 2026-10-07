"""Shrink big images before they are uploaded to a model."""
from __future__ import annotations
import os
from pathlib import Path
import re
import subprocess

SIPS = "/usr/bin/sips"


def image_size(path):
    """(width, height) in pixels, or None when macOS ``sips`` cannot read the file."""
    try:
        result = subprocess.run([SIPS, "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
                                capture_output=True, text=True, timeout=10)
        width = re.search(r"pixelWidth:\s*(\d+)", result.stdout)
        height = re.search(r"pixelHeight:\s*(\d+)", result.stdout)
        return (int(width.group(1)), int(height.group(1))) if width and height else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def shrink_image(path, max_edge=2048):
    """Scale the file at ``path`` in place so its longer side is at most ``max_edge`` pixels (JPEG, quality 85).
    Smaller images and any failure leave the file untouched. Returns True when it was resized."""
    if not max_edge or max_edge <= 0 or not Path(path).is_file():
        return False
    size = image_size(path)
    if size is None or max(size) <= max_edge:
        return False
    target = Path(str(path) + ".small.jpg")
    try:
        done = subprocess.run([SIPS, "-Z", str(int(max_edge)), "-s", "format", "jpeg", "-s", "formatOptions", "85",
                               str(path), "--out", str(target)], capture_output=True, timeout=20)
        if done.returncode or not target.is_file() or target.stat().st_size == 0:
            return False
        os.replace(target, path)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        Path(target).unlink(missing_ok=True)
