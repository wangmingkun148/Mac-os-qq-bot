"""Tray icon, UI windows and the application's main loop (the Windows counterpart of the menu-bar app)."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path

import pystray

from . import icons, win32
from .uia import top_level_windows  # noqa: F401  (re-exported for diagnostics)
from .webui import WebUI

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

TITLES = {"popover": "QQ 自动回复", "live": "QQ 自动回复 · 状态窗", "settings": "QQ 自动回复 · 设置"}
SIZES = {"popover": (400, 700), "live": (380, 640), "settings": (920, 680)}
WM_CLOSE = 0x0010
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOMOVE, SWP_NOSIZE, SWP_SHOWWINDOW = 0x0002, 0x0001, 0x0040
ERROR_ALREADY_EXISTS = 183
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_browser() -> str:
    """Edge (always present on Windows 10/11) or Chrome, used to show the UI in a chrome-less app window."""
    candidates = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidates += [Path(root) / "Microsoft/Edge/Application/msedge.exe", Path(root) / "Google/Chrome/Application/chrome.exe"]
    return next((str(path) for path in candidates if path.is_file()), "")


def work_area() -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)          # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


def find_window_by_title(title: str) -> int:
    found = []

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                # InPrivate/Incognito app windows append " - [InPrivate]" / " - Incognito" to the page title
                if buffer.value == title or buffer.value.startswith(title + " - "):
                    cls = ctypes.create_unicode_buffer(64)
                    user32.GetClassNameW(hwnd, cls, 64)
                    if cls.value == "Chrome_WidgetWin_1":
                        found.append(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else 0


class Windows:
    """Opens the UI pages as app-style browser windows and keeps at most one of each."""

    def __init__(self, app, web: WebUI):
        self.app = app
        self.web = web
        self.browser = find_browser()
        self.profile = app.base / "runtime" / "ui-profile"
        self.pinned = True
        self.command_id = 0
        self.command: dict = {}
        self._popover_watch: threading.Thread | None = None

    def open(self, kind: str, section: str | None = None):
        title = TITLES[kind]
        if section:
            self.command_id += 1
            self.command = {"id": self.command_id, "section": section}
        hwnd = find_window_by_title(title)
        if hwnd:
            win32.bring_to_front(hwnd)
            return
        view = {"popover": "/popover", "live": "/live", "settings": f"/settings/{section or 'general'}"}[kind]
        url = self.web.url(view)
        if not self.browser:
            webbrowser.open(url)
            return
        width, height = SIZES[kind]
        # Chromium's --window-size/--window-position are in device-independent pixels, the work area is physical
        scale = (user32.GetDpiForSystem() or 96) / 96
        left, top, right, bottom = (int(v / scale) for v in work_area())
        height = min(height, bottom - top - 24)
        if kind == "popover":
            x, y = right - width - 12, bottom - height - 12
        elif kind == "live":
            x, y = right - width - 24, top + 60
        else:
            width = min(width, right - left - 24)
            x, y = left + max(12, (right - left - width) // 2), top + max(12, (bottom - top - height) // 2)
        self.profile.mkdir(parents=True, exist_ok=True)
        # InPrivate + no sync: the window must never sign in to or sync with the user's Microsoft/Google account
        private = "--inprivate" if "msedge" in self.browser.lower() else "--incognito"
        args = [self.browser, f"--app={url}", f"--user-data-dir={self.profile}", f"--window-size={width},{height}",
                f"--window-position={x},{y}", private, "--no-first-run", "--no-default-browser-check", "--disable-extensions",
                "--disable-sync", "--disable-features=Translate,msEdgeSidebarV2,msImplicitSignin,msEdgeOnRamp,msEdgeShopping",
                "--disable-background-networking", "--disable-component-update", "--disable-default-apps"]
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=0x00000008)        # DETACHED_PROCESS
        threading.Thread(target=self._after_open, args=(kind, title), daemon=True).start()

    def _after_open(self, kind, title):
        for _ in range(60):
            hwnd = find_window_by_title(title)
            if hwnd:
                break
            time.sleep(0.2)
        else:
            return
        if kind == "live":
            self.apply_pin(hwnd)
        if kind == "popover":
            self._watch_popover(hwnd)

    def apply_pin(self, hwnd=None):
        hwnd = hwnd or find_window_by_title(TITLES["live"])
        if hwnd:
            user32.SetWindowPos(hwnd, HWND_TOPMOST if self.pinned else HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)

    def set_pinned(self, pinned: bool):
        self.pinned = bool(pinned)
        self.apply_pin()

    def close(self, kind: str):
        hwnd = find_window_by_title(TITLES[kind])
        if hwnd:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def close_all(self):
        for kind in TITLES:
            self.close(kind)

    def _watch_popover(self, hwnd):
        """Like a menu popover: it goes away when the user clicks somewhere else."""
        time.sleep(0.8)
        while user32.IsWindow(hwnd):
            time.sleep(0.25)
            foreground = win32.foreground_hwnd()
            if foreground != hwnd and not win32.window_pid(foreground) == win32.window_pid(hwnd):
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return


class Shell:
    def __init__(self, app, args):
        self.app = app
        self.args = args
        self.web = WebUI(app, self)
        self.windows = Windows(app, self.web)
        self.icon: pystray.Icon | None = None
        self.pet = None
        self._phase = None
        self._stop = threading.Event()

    # used by WebUI
    def open_window(self, kind, section=None):
        self.windows.open(kind, section)

    def set_pinned(self, pinned):
        self.windows.set_pinned(pinned)

    def quit(self):
        self._stop.set()
        if self.pet:
            self.pet.stop()
        self.app.shutdown()
        self.windows.close_all()
        if self.icon:
            self.icon.stop()

    # ------------------------------------------------------------------ tray
    def build_icon(self):
        phase = self.app.phase()
        menu = pystray.Menu(
            pystray.MenuItem("打开面板", lambda: self.windows.open("popover"), default=True),
            pystray.MenuItem("状态窗", lambda: self.windows.open("live")),
            pystray.MenuItem("设置", lambda: self.windows.open("settings", "general")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: "暂停" if not self.app.paused else "开始", self._toggle),
            pystray.MenuItem(lambda item: "隐藏桌宠" if (self.app.config.get("pet") or {}).get("enabled") else "显示桌宠",
                             lambda: self.app.set_pet_enabled(not (self.app.config.get("pet") or {}).get("enabled"))),
            pystray.MenuItem("打开配置文件", lambda: self.app.open_config_file()),
            pystray.MenuItem("打开项目文件夹", lambda: os.startfile(str(self.app.base))),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.quit()),
        )
        self.icon = pystray.Icon("qqchatbridge", icons.logo(64, phase), self.tooltip(), menu)
        self._phase = phase

    def tooltip(self) -> str:
        phase = self.app.phase()
        from .state import PHASE_LABELS
        return f"QQ 自动回复 · {PHASE_LABELS.get(phase, phase)}"

    def _toggle(self):
        self.app.toggle()
        if self.app.show_settings_requested:
            self.app.show_settings_requested = False
            self.windows.open("settings", "general")
        self.refresh_icon()

    def refresh_icon(self):
        if not self.icon:
            return
        phase = self.app.phase()
        if phase != self._phase:
            self._phase = phase
            try:
                self.icon.icon = icons.logo(64, phase)
            except Exception:
                pass
        try:
            self.icon.title = self.tooltip()
            self.icon.update_menu()
        except Exception:
            pass

    def notify(self, title, body):
        if self.icon:
            try:
                self.icon.notify(body, title)
            except Exception:
                pass

    def _ticker(self):
        while not self._stop.wait(2.0):
            self.refresh_icon()

    def _setup(self, icon):
        icon.visible = True
        threading.Thread(target=self._ticker, name="tray-refresh", daemon=True).start()
        app = self.app
        app.notify_sink = self.notify
        app.on_state_change = self.refresh_icon
        app.ensure_native()
        app.start_backend()
        try:
            from .pet import PetController
            self.pet = PetController(app, self)
            self.pet.start()
        except Exception:                 # the pet is a decoration: never let it stop the bot
            self.pet = None
        if self.args.start and not app.first_run and app.paused:
            app.toggle()
        from .app import configuration_problem
        problem = configuration_problem(app.config)
        if app.first_run or problem:
            self.windows.open("settings", "general")
        if self.args.show:
            time.sleep(0.5)
            self.windows.open(self.args.show, "general" if self.args.show == "settings" else None)

    def run(self) -> int:
        self.web.start()
        self.build_icon()
        try:
            self.icon.run(self._setup)
        finally:
            self.web.stop()
        return 0


def single_instance() -> bool:
    handle = kernel32.CreateMutexW(None, False, "Local\\QQChatBridgeWindows")
    return kernel32.GetLastError() != ERROR_ALREADY_EXISTS or not handle


def run_shell(app, args) -> int:
    if not single_instance():
        user32.MessageBoxW(None, "QQ 自动回复已经在运行，请在任务栏右下角的托盘里找到它。", "QQ 自动回复", 0x40)
        return 0
    return Shell(app, args).run()
