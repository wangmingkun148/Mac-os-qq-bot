"""Does the REAL QQ keep updating its accessibility tree while another window completely covers it?

Method (nothing is sent, nothing leaves the test group's window): collapse and re-open the group's member panel with
an accessibility Invoke while a second window covers QQ, and see whether the tree shows the change. The panel is put
back at the end. Takes about 25 seconds and briefly covers the QQ window.

    .venv\\Scripts\\python.exe -X utf8 tools\\test_occlusion_real.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import comtypes  # noqa: E402

from winapp import qqlaunch, tree as T, uia, win32  # noqa: E402
from winapp.qq import QQ  # noqa: E402

EDGE = next(str(p) for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
                             Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe") if p.is_file())


class Shell:
    config = {"groups": [], "reply_all_conversations": False}
    paused = False
    pending_send = False
    base = "."

    def typing_seconds(self):
        return 99

    def nativelog(self, line):
        pass


def panel_state(q):
    view = q.good_view()
    if view is None:
        return None, None
    wrapper = T.find_class(view.tree, "group-box__wrapper")
    toggle = T.find_class(view.tree, "group-box__toggle")
    rect = (wrapper or {}).get("rect")
    return (rect[2] - rect[0] if rect else 0), view.element(toggle)


def main():
    win32.set_dpi_aware()
    comtypes.CoInitialize()
    q = QQ(Shell())
    q.read_tree()
    time.sleep(0.5)
    print("QQ started with the occlusion switch:", bool(qqlaunch.flags_active()))
    width0, toggle = panel_state(q)
    if toggle is None:
        print("no member-panel toggle found (not a group chat?) - test not possible")
        return 1
    print("member panel width before:", width0)
    hwnd = q.find_window()[0]
    rect = uia.rect_of(uia.automation().ElementFromHandle(hwnd), cached=False)
    profile = tempfile.mkdtemp(prefix="qqbot-cover-")
    x, y, w, h = rect[0] - 40, rect[1] - 40, rect[2] - rect[0] + 80, rect[3] - rect[1] + 80
    cover = subprocess.Popen([EDGE, "--app=data:text/html,<title>cover</title><body style='background:%23222'><h1 style='color:%23fff'>covering QQ for a few seconds</h1>",
                              f"--user-data-dir={profile}", "--inprivate", "--no-first-run", "--disable-sync", "--disable-extensions",
                              f"--window-size={int(w / 1.5)},{int(h / 1.5)}", f"--window-position={int(x / 1.5)},{int(y / 1.5)}"])
    changed = None
    try:
        time.sleep(4)
        # make sure the cover really hides QQ completely (size/position flags are in device-independent pixels)
        import ctypes
        from ctypes import wintypes
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(handle, _):
            buffer = ctypes.create_unicode_buffer(64)
            ctypes.windll.user32.GetWindowTextW(handle, buffer, 64)
            if buffer.value.startswith("cover") and ctypes.windll.user32.IsWindowVisible(handle):
                found.append(handle)
            return True

        ctypes.windll.user32.EnumWindows(WNDENUMPROC(cb), 0)
        cover_hwnd = found[0] if found else 0
        if cover_hwnd:
            ctypes.windll.user32.MoveWindow(cover_hwnd, x, y, w, h, True)
            ctypes.windll.user32.SetWindowPos(cover_hwnd, 0, x, y, w, h, 0x0040)
            time.sleep(1.0)
            r = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(cover_hwnd, ctypes.byref(r))
            inside = r.left <= rect[0] and r.top <= rect[1] and r.right >= rect[2] and r.bottom >= rect[3]
            print("cover window found; completely hides QQ:", inside, "| cover", (r.left, r.top, r.right, r.bottom), "| QQ", tuple(rect))
        else:
            print("cover window NOT found")
        print("QQ is foreground while covered:", win32.foreground_is(q.find_window()[1]))
        uia.invoke(toggle)                        # collapse (or open) the member panel through accessibility
        time.sleep(2.5)
        width1, toggle2 = panel_state(q)
        changed = width1 != width0
        print("member panel width after toggling while covered:", width1, "-> tree is", "LIVE (updated)" if changed else "STALE (did not change)")
    finally:
        # put the panel back: bring QQ forward so the tree is live again, then toggle until the width is as before
        win32.bring_to_front(hwnd)
        time.sleep(1.5)
        for _ in range(3):
            width_now, toggle_now = panel_state(q)
            if width_now == width0 or toggle_now is None:
                break
            uia.invoke(toggle_now)
            time.sleep(1.5)
        print("member panel width restored:", panel_state(q)[0] == width0)
        cover.terminate()
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -match 'qqbot-cover' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                       capture_output=True)
    return 0 if changed is not None else 1


if __name__ == "__main__":
    sys.exit(main())
