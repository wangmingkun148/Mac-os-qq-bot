"""Win32 helpers: synthetic mouse/keyboard input, foreground-window control and typing detection."""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE, KEYEVENTF_SCANCODE = 0x0002, 0x0004, 0x0008
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800
VK_BACK, VK_RETURN, VK_SHIFT, VK_CONTROL, VK_MENU, VK_ESCAPE, VK_END, VK_DELETE = 0x08, 0x0D, 0x10, 0x11, 0x12, 0x1B, 0x23, 0x2E
VK_A, VK_C, VK_V = 0x41, 0x43, 0x56
SW_RESTORE, SW_SHOW = 9, 5

# every event we inject carries this tag, so the typing detector can tell our keystrokes from the user's
INJECT_TAG = 0x51514254


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _InputUnion)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def set_dpi_aware():
    """Make coordinates physical pixels, matching what UI Automation reports. Call once, before any window exists."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor
    except (AttributeError, OSError):
        try:
            user32.SetProcessDPIAware()
        except AttributeError:
            pass


def _send(events: list[INPUT]):
    if not events:
        return
    array = (INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    if sent != len(events):
        raise OSError(f"SendInput delivered {sent}/{len(events)} events (blocked by a higher-privilege window?)")


def _key_event(vk=0, scan=0, flags=0):
    event = INPUT(type=INPUT_KEYBOARD)
    event.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=INJECT_TAG)
    return event


def _mouse_event(flags, data=0):
    event = INPUT(type=INPUT_MOUSE)
    event.mi = MOUSEINPUT(dx=0, dy=0, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=INJECT_TAG)
    return event


# --- keyboard ----------------------------------------------------------------------------------------------

def press_key(vk: int, *modifiers: int):
    """Tap ``vk`` while holding the given modifier virtual keys."""
    events = [_key_event(m) for m in modifiers]
    events += [_key_event(vk), _key_event(vk, flags=KEYEVENTF_KEYUP)]
    events += [_key_event(m, flags=KEYEVENTF_KEYUP) for m in reversed(modifiers)]
    _send(events)


def type_text(text: str, chunk: int = 24, pause: float = 0.01):
    """Type ``text`` as Unicode key events (no clipboard involved, independent of the keyboard layout/IME)."""
    units = []
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        units.append(int.from_bytes(data[i:i + 2], "little"))
    for start in range(0, len(units), chunk):
        events = []
        for unit in units[start:start + chunk]:
            events.append(_key_event(0, unit, KEYEVENTF_UNICODE))
            events.append(_key_event(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
        _send(events)
        time.sleep(pause)


# --- mouse -------------------------------------------------------------------------------------------------

def cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def move_cursor(x: int, y: int):
    user32.SetCursorPos(int(x), int(y))


def click(x: int, y: int, right: bool = False, restore: bool = True):
    """Click at screen position (x, y); the cursor goes back where it was afterwards."""
    before = cursor_pos()
    move_cursor(x, y)
    time.sleep(0.03)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if right else (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    _send([_mouse_event(down)])
    time.sleep(0.03)
    _send([_mouse_event(up)])
    if restore:
        time.sleep(0.05)
        move_cursor(*before)


def scroll_wheel(x: int, y: int, clicks: int):
    """Wheel scroll at (x, y); positive = up."""
    move_cursor(x, y)
    _send([_mouse_event(MOUSEEVENTF_WHEEL, clicks * 120 & 0xFFFFFFFF)])


# --- windows -----------------------------------------------------------------------------------------------

user32.GetForegroundWindow.restype = wintypes.HWND
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.BringWindowToTop.argtypes = [wintypes.HWND]


def foreground_hwnd() -> int:
    return user32.GetForegroundWindow() or 0


def window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_window(hwnd) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def bring_to_front(hwnd) -> bool:
    """Restore and focus ``hwnd`` even though Windows normally forbids background processes from stealing focus."""
    if not is_window(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    elif not user32.IsWindowVisible(hwnd):
        user32.ShowWindow(hwnd, SW_SHOW)
    if foreground_hwnd() == hwnd:
        return True
    current = foreground_hwnd()
    my_thread = kernel32.GetCurrentThreadId()
    their_thread = user32.GetWindowThreadProcessId(current, None) if current else 0
    attached = False
    try:
        if their_thread and their_thread != my_thread:
            attached = bool(user32.AttachThreadInput(my_thread, their_thread, True))
        # a tap on Alt convinces Windows the user is interacting, which lifts the foreground lock
        _send([_key_event(VK_MENU), _key_event(VK_MENU, flags=KEYEVENTF_KEYUP)])
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(my_thread, their_thread, False)
    for _ in range(10):
        if foreground_hwnd() == hwnd:
            return True
        time.sleep(0.03)
    return foreground_hwnd() == hwnd


def foreground_is(pid: int) -> bool:
    hwnd = foreground_hwnd()
    return bool(hwnd) and window_pid(hwnd) == pid


# --- typing detection --------------------------------------------------------------------------------------

WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class _LastInputInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


class TypingWatcher:
    """Remembers when the user last pressed a key. Keys we inject ourselves are ignored.

    Uses a low-level keyboard hook (it only records a timestamp); when the hook cannot be installed it falls back
    to ``GetLastInputInfo`` (keyboard *and* mouse)."""

    def __init__(self):
        self.last = None
        self.hook_ok = False
        self._thread = None
        self._ready = threading.Event()
        self._proc = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="typing-watch", daemon=True)
        self._thread.start()
        self._ready.wait(2)

    def _run(self):
        def proc(code, wparam, lparam):
            if code >= 0 and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if info.dwExtraInfo != INJECT_TAG:
                    self.last = time.monotonic()
            return user32.CallNextHookEx(None, code, wparam, lparam)

        self._proc = HOOKPROC(proc)
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        self.hook_ok = bool(hook)
        self._ready.set()
        if not hook:
            return
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        user32.UnhookWindowsHookEx(hook)

    def seconds_since_typing(self) -> float:
        if self.hook_ok:
            return float("inf") if self.last is None else time.monotonic() - self.last
        info = _LastInputInfo(cbSize=ctypes.sizeof(_LastInputInfo))
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return float("inf")
        return max(0.0, (kernel32.GetTickCount() - info.dwTime) / 1000.0)
