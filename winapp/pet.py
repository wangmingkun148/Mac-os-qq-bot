"""The desktop pet: a pixel wolf in a borderless, transparent, always-on-top window (port of the macOS PetView/PetBrain).

It reacts to what the bot is doing: ears up when a message arrives, thinking dots while the model works, talking
with the reply in a bubble, yawning when it chooses not to answer, dizzy on errors, asleep when paused or idle.
Click it for a little animation, drag it anywhere, right-click for a menu.

tkinter needs one thread of its own; everything the pet reads from the app is plain data."""
from __future__ import annotations

import json
import random
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KEY = (1, 2, 3)                      # colour the window treats as transparent
KEY_HEX = "#010203"


def asset(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "winapp" / name
    return Path(__file__).resolve().parent / name


ART = json.loads(asset("pet_art.json").read_text(encoding="utf-8"))
WIDTH, HEIGHT = ART["width"], ART["height"]
PALETTE = {char: tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) for char, value in ART["palette"].items()}
FRAMES: dict[str, list[list[str]]] = ART["frames"]

RISE = ["up_pre", "up_0", "up_1", "up_2"]


def frame_rows(key: str, index: int) -> list[str]:
    frames = FRAMES.get(key) or FRAMES["idle"]
    return frames[index % len(frames)]


def frame_count(key: str) -> int:
    return len(FRAMES.get(key) or FRAMES["idle"])


def transition(from_pose: str, to_pose: str) -> list[str]:
    """Bridge frames played before ``to_pose`` so poses do not snap."""
    wake = ["in_sleep", "in_idle"] if from_pose == "sleep" else []
    if to_pose == "walk":
        return [] if from_pose == "walk" else wake + RISE
    if from_pose == "walk":
        return RISE[::-1] + ([] if to_pose == "idle" else [f"in_{to_pose}"])
    if from_pose == "sleep":
        return wake
    return ["in_idle"] if to_pose == "idle" else [f"in_{to_pose}"]


def steps(key: str) -> int:
    return 1 if key.startswith("up_") else 2


def frame_index(pose: str, tick: int) -> int:
    if pose == "idle":
        return [0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0, 2, 0, 0, 1, 1][tick % 18]
    if pose == "walk":
        return tick % 4
    if pose in ("talk", "alert", "dizzy"):
        return (tick // 2) % 2
    if pose == "think":
        return (tick // 3) % 4
    if pose == "yawn":
        return [0, 1, 1, 1, 1, 0][tick % 6]
    if pose == "sleep":
        return (tick // 6) % 2
    return 0


def reaction_script(name: str) -> list[tuple[str, int, str | None]]:
    """(sprite key, frame, bubble) per animation step (0.15 s); starts with a bridge frame, ends with in_idle."""
    if name == "wag":
        return [("in_wag", 0, None)] * 2 + [("wag", i % 4, "♥" if i % 4 == 1 else None) for i in range(14)] + [("in_idle", 0, None)] * 2
    return [("in_howl", 0, None)] * 2 + [("howl", (i // 2) % 2, "嗷呜～") for i in range(14)] + [("in_howl", 0, None)] * 2 + [("in_idle", 0, None)] * 2


REACTIONS = ("wag", "howl")


def sprite_image(key: str, index: int, scale: int, flip: bool = False) -> Image.Image:
    rows = frame_rows(key, index)
    image = Image.new("RGB", (WIDTH, HEIGHT), KEY)
    pixels = image.load()
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            color = PALETTE.get(char)
            if color:
                pixels[x, y] = color
    if flip:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    return image.resize((WIDTH * scale, HEIGHT * scale), Image.NEAREST)


# --- what the pet should feel -----------------------------------------------------------------------------------

@dataclass
class Mood:
    pose: str
    bubble: str | None = None


def clip(text: str, limit: int = 70) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


def current_turn(live: dict):
    preview = (live.get("preview") or {}).get("turn")
    return next((t for t in live.get("turns", []) if not t.get("outcome") and t.get("id") != preview), None)


def finished_turns(live: dict) -> list:
    return [t for t in live.get("turns", []) if t.get("outcome")]


class Brain:
    """Turns the bot's live state into a mood (pure logic, no UI)."""

    def __init__(self):
        self.reaction = None            # (pose, until, bubble)
        self.seen: set = set()
        self.handled: set = set()
        self.last_waiting = 0
        self.last_unvisited = 0
        self.primed = False
        self.last_activity = 0.0
        self.idle_sleep_after = 300.0

    def update(self, live: dict, phase: str, paused: bool, config_error, now: float) -> Mood:
        if not self.primed:
            self._prime(live)
            self.primed = True
            self.last_activity = now
        if paused:
            self.reaction = None
            self.last_activity = now
            return Mood("sleep")
        if config_error:
            return Mood("dizzy", clip(config_error.replace("配置有误，后台没有启动：", "配置有误："), 40))
        if phase == "offline":
            return Mood("dizzy", "后台没有响应")
        current = current_turn(live)
        if phase == "attention" and current is None:
            return Mood("dizzy", clip((live.get("engine") or {}).get("message") or "需要注意", 40))
        self._observe(live, now, current)
        if self.reaction and self.reaction[1] > now:
            self.last_activity = now
            return Mood(self.reaction[0], self.reaction[2])
        self.reaction = None
        if current:
            self.last_activity = now
            if current.get("stage") in ("ready", "sending", "verifying"):
                text = clip((current.get("reply") or {}).get("text") or "") or None
                return Mood("talk" if text else "think", text)
            return Mood("think")
        if now - self.last_activity >= self.idle_sleep_after:
            return Mood("sleep")
        return Mood("idle")

    def _prime(self, live):
        self.seen = {t["id"] for t in live.get("turns", [])}
        self.handled = {t["id"] for t in finished_turns(live)}
        self.last_waiting = sum(w.get("count", 0) for w in live.get("waiting", []))
        self.last_unvisited = len(live.get("unvisited") or [])

    def _observe(self, live, now, current):
        for turn in reversed(finished_turns(live)):            # oldest first, so the newest one wins
            if turn["id"] in self.handled:
                continue
            self.handled.add(turn["id"])
            self.seen.add(turn["id"])
            if time.time() - (turn.get("ended") or turn.get("started") or 0) >= 30:
                continue
            outcome = turn.get("outcome")
            if outcome == "replied":
                text = (turn.get("reply") or {}).get("text")
                self.reaction = ("talk", now + 5, clip(text) if text else None)
            elif outcome == "silent":
                self.reaction = ("yawn", now + 3, "不接话：" + clip((turn.get("decision") or {}).get("reason") or "没什么好说的", 36))
            elif outcome in ("failed", "uncertain", "abandoned"):
                last = (turn.get("timeline") or [{}])[-1].get("text") if turn.get("timeline") else None
                self.reaction = ("dizzy", now + 5, clip(turn.get("error") or last or "出错了", 44))
        startled = False
        if current and current["id"] not in self.seen:
            self.seen.add(current["id"])
            startled = True
        waiting = sum(w.get("count", 0) for w in live.get("waiting", []))
        if waiting > self.last_waiting:
            startled = True
        self.last_waiting = waiting
        unvisited = len(live.get("unvisited") or [])
        if unvisited > self.last_unvisited:
            startled = True
        self.last_unvisited = unvisited
        if startled:
            self.last_activity = now
            if self.reaction is None or self.reaction[1] <= now or self.reaction[0] == "yawn":
                self.reaction = ("alert", now + 1.4, None)


class Model:
    """Mood + animation + wandering. ``step`` runs every 0.15 s."""

    def __init__(self, brain: Brain | None = None):
        self.brain = brain or Brain()
        self.mood = Mood("idle")
        self.tick = 0
        self.sprite = ("idle", 0)
        self.walking = False
        self.facing_left = False
        self.reaction_bubble: str | None = None
        self.enabled, self.wander_enabled, self.bubble_enabled = True, True, True
        self._last_pose: str | None = None
        self._transition: list[str] = []
        self._transition_ticks = 0
        self._next_walk = time.time() + 6
        self._walk_remaining = 0.0
        self._paused_until = 0.0
        self._reaction: list = []
        self._pending: str | None = None
        self._last_reaction: str | None = None
        self.move = None                # callable(dx) -> bool
        self.room = None                # callable() -> (left, right)

    def user_moved(self):
        self.walking = False
        self._walk_remaining = 0
        self._paused_until = time.time() + 10
        self._pending = None

    def poke(self, choice: str | None = None, now: float | None = None):
        now = time.time() if now is None else now
        if not self.enabled or self._reaction or self._pending or self.mood.pose not in ("idle", "walk"):
            return
        options = [r for r in REACTIONS if r != self._last_reaction]
        self._pending = choice or random.choice(options)
        self.walking = False
        self._walk_remaining = 0
        self._paused_until = now + 8
        self._next_walk = now + 10

    def step(self, live: dict, phase: str, paused: bool, config_error, now: float | None = None):
        now = time.time() if now is None else now
        self.tick += 1
        mood = self.brain.update(live, phase, paused, config_error, now)
        if not self.bubble_enabled:
            mood.bubble = None
        if mood.pose != "idle":
            self.walking = False
            self._walk_remaining = 0
            self._next_walk = now + 8
            self._reaction = []
            self._pending = None
        if mood.pose == "idle" and not self._reaction:
            self._wander(now)
        if self.walking:
            mood = Mood("walk")
        if self._last_pose is not None and self._last_pose != mood.pose:
            self._transition = [key for key in transition(self._last_pose, mood.pose) for _ in range(steps(key))]
            self._transition_ticks = 0
        self._last_pose = mood.pose
        self.mood = mood
        if mood.pose == "idle" and not self.walking and not self._transition and not self._reaction and self._pending:
            chosen, self._pending = self._pending, None
            self._last_reaction = chosen
            self._reaction = reaction_script(chosen)
        shown = None
        if self._reaction and not self._transition:
            key, index, shown = self._reaction.pop(0)
            self.sprite = (key, index)
            self._next_walk = now + 8
        elif self._transition:
            self.sprite = (self._transition[min(self._transition_ticks, len(self._transition) - 1)], 0)
            self._transition_ticks += 1
            if self._transition_ticks >= len(self._transition):
                self._transition = []
        else:
            self.sprite = (mood.pose, frame_index(mood.pose, self.tick))
        if self.bubble_enabled:
            self.reaction_bubble = shown

    def bubble_text(self) -> str | None:
        if self.mood.bubble or self.reaction_bubble:
            return self.mood.bubble or self.reaction_bubble
        if self.mood.pose == "think" and self.bubble_enabled:
            return "·" * (1 + (self.tick // 3) % 3)
        return None

    def _wander(self, now):
        if not self.wander_enabled or now <= self._paused_until:
            self.walking = False
            return
        if self.walking:
            if self._last_pose != "walk" or self._transition:
                return                                       # rising: stay put until the wolf is on its feet
            step = 7
            delta = -step if self.facing_left else step
            if self._walk_remaining <= 0 or (self.move and self.move(delta) is False):
                self.walking = False
                self._next_walk = now + random.uniform(6, 18)
                return
            self._walk_remaining -= step
            return
        if now < self._next_walk or not self.room:
            return
        left, right = self.room()
        go_left = left > 80 and (right < 80 or random.random() < 0.5)
        if (left if go_left else right) <= 60:
            self._next_walk = now + 5
            return
        self.facing_left = go_left
        self._walk_remaining = random.uniform(70, 260)
        self.walking = True


# --- the window --------------------------------------------------------------------------------------------------

def system_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


_FONTS: dict = {}


def glyph_bytes(font, char: str) -> bytes:
    image = Image.new("L", (20, 20), 0)
    ImageDraw.Draw(image).text((2, 2), char, font=font, fill=255)
    return image.tobytes()


def char_font(char: str):
    """Ark Pixel for the characters it has, a system CJK font for the rest (the pixel font is a subset)."""
    if not _FONTS:
        main = ImageFont.truetype(str(asset("ui/ArkPixel12.otf")), 12)
        fallback = None
        windows = Path(__import__("os").environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("msyh.ttc", "simsun.ttc", "msjh.ttc"):
            try:
                fallback = ImageFont.truetype(str(windows / name), 12)
                break
            except OSError:
                continue
        _FONTS.update(main=main, fallback=fallback, tofu=glyph_bytes(main, "\uFFFF"), cache={})
    cache = _FONTS["cache"]
    if char not in cache:
        missing = glyph_bytes(_FONTS["main"], char) == _FONTS["tofu"]
        cache[char] = _FONTS["fallback"] if (missing and _FONTS["fallback"]) else _FONTS["main"]
    return cache[char]


def text_width(probe, text: str) -> float:
    return sum(probe.textlength(char, font=char_font(char)) for char in text)


def draw_text(draw, x: float, y: float, text: str, fill):
    for char in text:
        font = char_font(char)
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font)


def bubble_image(text: str, dark: bool) -> Image.Image:
    card, border, ink = ((26, 31, 42), (42, 49, 66), (233, 237, 245)) if dark else ((255, 255, 255), (215, 221, 232), (20, 26, 38))
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines, line = [], ""
    for char in text:
        if text_width(probe, line + char) > 188:
            lines.append(line)
            line = char
        else:
            line += char
    lines.append(line)
    lines = lines[:3]
    width = int(max(text_width(probe, l) for l in lines)) + 22
    height = len(lines) * 17 + 16
    image = Image.new("RGB", (width + 2, height + 12), KEY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, width + 1, height + 1), fill=border)          # hard shadow
    draw.rectangle((0, 0, width - 1, height - 1), fill=card, outline=border)
    for i, l in enumerate(lines):
        draw_text(draw, 11, 8 + i * 17, l, ink)
    mid = width // 2
    for i, (w, color) in enumerate(((12, card), (6, card))):          # stair-stepped tail
        y = height + i * 3
        draw.rectangle((mid - w // 2, y, mid + w // 2, y + 2), fill=color, outline=border)
    draw.rectangle((mid - 3, height + 6, mid + 3, height + 6), fill=border)
    return image


class PetController:
    def __init__(self, app, shell=None):
        self.app = app
        self.shell = shell
        self.model = Model()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.ok = True

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="pet", daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    # settings -------------------------------------------------------------------------------------------------
    def settings(self) -> dict:
        pet = self.app.config.get("pet") or {}
        return {"enabled": bool(pet.get("enabled", False)), "scale": max(1, min(12, int(pet.get("scale", 4) or 4))),
                "wander": bool(pet.get("wander", True)), "bubble": bool(pet.get("bubble", True))}

    def _origin_file(self) -> Path:
        return self.app.base / "runtime" / "ui-prefs.json"

    def _load_origin(self):
        try:
            return json.loads(self._origin_file().read_text(encoding="utf-8")).get("pet_origin")
        except (OSError, json.JSONDecodeError):
            return None

    def _save_origin(self, x, y):
        path = self._origin_file()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        data["pet_origin"] = [x, y]
        try:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    # tk loop --------------------------------------------------------------------------------------------------
    def _run(self):
        try:
            import tkinter as tk
            from PIL import ImageTk
        except ImportError:
            self.ok = False
            return
        from . import shell as shell_module
        root = tk.Tk()
        root.withdraw()
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.attributes("-transparentcolor", KEY_HEX)
        win.configure(bg=KEY_HEX)
        canvas = tk.Canvas(win, bg=KEY_HEX, highlightthickness=0, bd=0)
        canvas.pack()
        win.withdraw()
        state = {"scale": 0, "shown": False, "drag": None, "images": [], "last": None, "x": 0, "y": 0, "w": 0, "h": 0}
        model = self.model

        def window_size(scale):
            return max(WIDTH * scale, 250), HEIGHT * scale + 120

        def place(x, y):
            state["x"], state["y"] = int(x), int(y)
            win.geometry(f"{state['w']}x{state['h']}+{int(x)}+{int(y)}")

        def apply_scale(scale):
            old_w, old_h = state["w"], state["h"]
            state["scale"] = scale
            state["w"], state["h"] = window_size(scale)
            canvas.configure(width=state["w"], height=state["h"])
            if state["shown"]:                                  # keep the feet where they were
                place(state["x"] + (old_w - state["w"]) / 2, state["y"] + (old_h - state["h"]))
            else:
                left, top, right, bottom = shell_module.work_area()
                saved = self._load_origin()
                if saved and left - 100 < saved[0] < right and top - 20 < saved[1] < bottom:
                    place(saved[0], saved[1])
                else:
                    place(right - state["w"] - 30, bottom - state["h"] - 6)
            state["last"] = None

        def room():
            left, _, right, _ = shell_module.work_area()
            sprite_w = WIDTH * state["scale"]
            sprite_left = state["x"] + (state["w"] - sprite_w) / 2
            return sprite_left - left, right - (sprite_left + sprite_w)

        def move(dx):
            if state["drag"]:
                return False
            left, right = room()
            if (dx < 0 and left < -dx) or (dx > 0 and right < dx):
                return False
            place(state["x"] + dx, state["y"])
            return True

        model.move, model.room = move, room

        def redraw():
            scale = state["scale"]
            key, index = model.sprite
            flip = model.facing_left and model.walking
            bubble = model.bubble_text() if model.bubble_enabled else None
            signature = (key, index, flip, bubble, scale, system_dark() if bubble else None)
            if signature == state["last"]:
                return
            state["last"] = signature
            canvas.delete("all")
            images = []
            sprite = ImageTk.PhotoImage(sprite_image(key, index, scale, flip))
            images.append(sprite)
            sx, sy = (state["w"] - WIDTH * scale) // 2, state["h"] - HEIGHT * scale
            item = canvas.create_image(sx, sy, image=sprite, anchor="nw")
            if bubble:
                picture = ImageTk.PhotoImage(bubble_image(bubble, system_dark()))
                images.append(picture)
                bx = int(state["w"] / 2 - picture.width() / 2 + scale * 5)
                by = max(0, sy - picture.height() - 2)
                canvas.create_image(min(max(0, bx), state["w"] - picture.width()), by, image=picture, anchor="nw")
            state["images"] = images
            canvas.tag_bind(item, "<ButtonPress-1>", press)
            canvas.tag_bind(item, "<B1-Motion>", drag)
            canvas.tag_bind(item, "<ButtonRelease-1>", release)
            canvas.tag_bind(item, "<Button-3>", popup)

        def press(event):
            state["drag"] = {"mouse": (event.x_root, event.y_root), "origin": (state["x"], state["y"]), "moved": False}

        def drag(event):
            d = state["drag"]
            if not d:
                return
            dx, dy = event.x_root - d["mouse"][0], event.y_root - d["mouse"][1]
            if not d["moved"] and abs(dx) + abs(dy) < 4:
                return
            if not d["moved"]:
                d["moved"] = True
                model.user_moved()
            place(d["origin"][0] + dx, d["origin"][1] + dy)

        def release(event):
            d, state["drag"] = state["drag"], None
            if d and d["moved"]:
                self._save_origin(state["x"], state["y"])
                model.user_moved()
            elif d:
                model.poke()

        menu = tk.Menu(win, tearoff=0)

        def popup(event):
            menu.delete(0, "end")
            menu.add_command(label="打开实时状态小窗", command=lambda: self.shell and self.shell.open_window("live"))
            menu.add_command(label="设置…", command=lambda: self.shell and self.shell.open_window("settings", "general"))
            menu.add_command(label="暂停 / 继续自动回复", command=lambda: threading.Thread(target=self.app.toggle, daemon=True).start())
            menu.add_command(label="隐藏桌宠", command=lambda: self.app.set_pet_enabled(False))
            menu.tk_popup(event.x_root, event.y_root)

        def tick():
            if self._stop.is_set():
                root.destroy()
                return
            try:
                settings = self.settings()
                model.enabled, model.wander_enabled, model.bubble_enabled = settings["enabled"], settings["wander"], settings["bubble"]
                if not settings["enabled"]:
                    if state["shown"]:
                        win.withdraw()
                        state["shown"] = False
                else:
                    if state["scale"] != settings["scale"]:
                        apply_scale(settings["scale"])
                    if not state["shown"]:
                        win.deiconify()
                        win.attributes("-topmost", True)
                        state["shown"] = True
                    engine = self.app.engine
                    live = engine.live.snapshot() if engine is not None else {"turns": [], "waiting": [], "unvisited": [], "engine": {}}
                    status = engine.status if engine is not None else {}
                    error = status.get("message") if status.get("state") == "config_error" else None
                    model.step(live, self.app.phase(), self.app.paused, error)
                    redraw()
            except Exception:
                pass
            root.after(150, tick)

        apply_scale(self.settings()["scale"])
        root.after(150, tick)
        root.mainloop()
        # release every Tk object on this thread, or Python aborts at exit ("Tcl_AsyncDelete: wrong thread")
        state["images"] = []
        canvas = win = menu = root = None
        import gc
        gc.collect()
