"""The pixel-art wolf "Q" logo, drawn with Pillow (tray icon and window icon)."""
from __future__ import annotations

from PIL import Image, ImageDraw

# '#' body, 'c' accent (the tail of the Q). Same art as the macOS app (Sources/UI/Theme.swift WolfArt).
ROWS = [
    "................",
    "..##........##..",
    "..###......###..",
    "..####.##.####..",
    "..############..",
    ".####......####.",
    ".###........###.",
    ".###........###.",
    ".###........###.",
    ".####......####.",
    "..####....#####.",
    "...##########cc.",
    "....########.ccc",
    "..............cc",
    "................",
    "................",
]
BODY = (238, 242, 250, 255)
ACCENT = (111, 211, 232, 255)
TILE = (20, 24, 34, 255)
EDGE = (43, 51, 69, 255)
RED = (255, 122, 122, 255)
AMBER = (242, 201, 76, 255)
GREEN = (127, 217, 154, 255)


def logo(size: int = 64, phase: str = "listening") -> Image.Image:
    """The logo on its dark tile. ``paused`` dims it, ``attention``/``offline`` add a red mark, busy phases a cyan dot."""
    scale = max(1, size // 16)
    art = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    pixels = art.load()
    rows = [list(row) for row in ROWS]
    if phase in ("attention", "offline"):
        for x, y in ((7, 6), (8, 6), (7, 7), (8, 7), (7, 8), (8, 8), (7, 10), (8, 10)):
            rows[y][x] = "!"
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char == "#":
                pixels[x, y] = BODY
            elif char == "c":
                pixels[x, y] = ACCENT
            elif char == "!":
                pixels[x, y] = RED
    if phase == "paused":                       # dither: every other pixel gone
        for y in range(16):
            for x in range(16):
                if (x + y) % 2 == 0:
                    pixels[x, y] = (0, 0, 0, 0)
    art = art.resize((16 * scale, 16 * scale), Image.NEAREST)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(2, size // 5), fill=TILE, outline=EDGE, width=max(1, size // 32))
    offset = (size - art.width) // 2
    canvas.alpha_composite(art, (offset, offset))
    if phase in ("thinking", "starting", "switching", "sending"):
        dot = max(3, size // 6)
        draw.rectangle((size - dot - 1, 1, size - 2, dot), fill=ACCENT)
    elif phase == "waiting":
        dot = max(3, size // 6)
        draw.rectangle((size - dot - 1, 1, size - 2, dot), fill=AMBER)
    return canvas


def save_ico(path, sizes=(16, 24, 32, 48, 64, 128, 256)):
    logo(256).save(path, format="ICO", sizes=[(s, s) for s in sizes])
