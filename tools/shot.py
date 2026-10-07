"""Developer helper: save a screenshot of the window with the given title.   shot.py "title" out.png"""
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

ctypes.windll.shcore.SetProcessDpiAwareness(2)
user32 = ctypes.WinDLL("user32")
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find(title):
    found = []

    def cb(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value == title:
                found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0] if found else 0


hwnd = find(sys.argv[1])
if not hwnd:
    print("window not found")
    sys.exit(1)
rect = wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
print("rect", rect.left, rect.top, rect.right, rect.bottom)
ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(Path(sys.argv[2]))
