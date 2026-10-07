"""Developer check for the desktop pet.

    dev_pet.py sheet out.png     contact sheet of every pose (no window)
    dev_pet.py run               show the real pet window for ~12 s with a scripted sequence of moods
"""
import ctypes
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from winapp import pet, win32  # noqa: E402


def sheet(target):
    poses = [("idle", 0), ("idle", 1), ("alert", 0), ("think", 1), ("talk", 0), ("yawn", 1), ("dizzy", 0), ("sleep", 0), ("walk", 0), ("walk", 2),
             ("wag", 1), ("howl", 0)]
    scale = 4
    cell_w, cell_h = pet.WIDTH * scale + 8, pet.HEIGHT * scale + 8
    canvas = Image.new("RGB", (cell_w * 6, cell_h * 2 + 140), (40, 44, 56))
    for i, (key, index) in enumerate(poses):
        canvas.paste(pet.sprite_image(key, index, scale), ((i % 6) * cell_w + 4, (i // 6) * cell_h + 4))
    bubble = pet.bubble_image("回复内容会显示在这里，最多三行，超过的部分会被截掉……", True)
    canvas.paste(bubble, (10, cell_h * 2 + 10))
    canvas.paste(pet.bubble_image("不接话：只是笑声", False), (420, cell_h * 2 + 10))
    canvas.save(target)
    print("wrote", target)


class FakeEngine:
    def __init__(self):
        from live_feed import LiveFeed
        self.live = LiveFeed(Path(tempfile.mkdtemp()) / "live.json")
        self.status = {"state": "listening"}


class FakeApp:
    def __init__(self):
        self.base = Path(tempfile.mkdtemp())
        (self.base / "runtime").mkdir()
        self.config = {"pet": {"enabled": True, "scale": 4, "wander": True, "bubble": True}}
        self.engine = FakeEngine()
        self.paused = False
        self.mood = "listening"

    def phase(self):
        return "paused" if self.paused else self.mood

    def set_pet_enabled(self, on):
        self.config["pet"]["enabled"] = on

    def toggle(self):
        self.paused = not self.paused


def run():
    win32.set_dpi_aware()
    app = FakeApp()
    controller = pet.PetController(app)
    controller.start()
    time.sleep(2)
    live = app.engine.live
    turn = live.begin("g", "g", "reply", [{"id": "1", "sender": "x", "text": "hi", "has_image": False}])
    time.sleep(2)
    live.update(turn, reply={"text": "来了来了～"})
    live.step(turn, "sending", "sending")
    time.sleep(3)
    live.finish(turn, "replied", "ok")
    time.sleep(3)
    user32 = ctypes.WinDLL("user32")
    found = []

    def cb(hwnd, _):
        buffer = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, buffer, 64)
        if buffer.value == "TkTopLevel" and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            exstyle = user32.GetWindowLongW(hwnd, -20)
            found.append((rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top, bool(exstyle & 0x8), bool(exstyle & 0x80000)))
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    print("pet windows (x, y, w, h, topmost, layered):", found)
    model = controller.model
    print("mood:", model.mood, "sprite:", model.sprite, "walking:", model.walking)
    app.config["pet"]["enabled"] = False
    time.sleep(1)
    controller.stop()
    time.sleep(0.5)


if __name__ == "__main__":
    if sys.argv[1] == "sheet":
        sheet(sys.argv[2])
    else:
        run()
