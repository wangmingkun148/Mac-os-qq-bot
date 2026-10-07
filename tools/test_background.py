"""Does the mock QQ keep updating its accessibility tree when another window covers it / when it is minimised?

    .venv\\Scripts\\python.exe -X utf8 tools\\test_background.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "fake_qq"))
os.environ["QQBOT_TEST_PROCESS"] = "msedge.exe"

import comtypes  # noqa: E402

from server import FakeQQ  # noqa: E402
from snapshot import parse_snapshot  # noqa: E402
from winapp import uia, win32  # noqa: E402
from winapp.qq import QQ  # noqa: E402

EDGE = next(str(p) for p in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
                             Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe") if p.is_file())
CONFIG = {"groups": ["测试群"], "self_names": ["小我"], "reply_all_conversations": False}


class Shell:
    config = CONFIG
    paused = False
    pending_send = False
    base = tempfile.mkdtemp()

    def typing_seconds(self):
        return 99

    def nativelog(self, line):
        print("  LOG", line)


def messages(q):
    snap = q.snapshot()
    if "error" in snap:
        return snap["error"]
    parsed = parse_snapshot(snap, CONFIG)
    return [m["text"] for m in parsed["messages"]]


def main():
    win32.set_dpi_aware()
    comtypes.CoInitialize()
    fake = FakeQQ()
    profile = tempfile.mkdtemp(prefix="qqbot-fake-edge-")
    keep_awake = "--keepawake" in sys.argv         # launch the mock QQ with the flags meant to stop occlusion throttling
    features = "msImplicitSignin,msEdgeOnRamp" + (",CalculateNativeWinOcclusion" if keep_awake else "")
    extra = ["--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"] if keep_awake else []
    print("flags:", "occlusion tracking disabled" if keep_awake else "default", flush=True)
    subprocess.Popen([EDGE, f"--app={fake.url}", f"--user-data-dir={profile}", "--inprivate", "--no-first-run", "--window-size=1000,700",
                      "--window-position=60,60", "--disable-sync", "--disable-extensions", f"--disable-features={features}", *extra])
    q = QQ(Shell())
    for _ in range(60):
        if q.find_window():
            break
        time.sleep(0.3)
    time.sleep(1)
    q.read_tree()
    time.sleep(2)
    print("visible, foreground  :", messages(q)[-2:], flush=True)

    # a second browser window that covers the mock QQ completely
    cover_profile = tempfile.mkdtemp(prefix="qqbot-fake-edge-")
    subprocess.Popen([EDGE, "--app=data:text/html,<title>cover</title><h1>covering window</h1>", f"--user-data-dir={cover_profile}", "--inprivate",
                      "--no-first-run", "--window-size=1150,850", "--window-position=20,20", "--disable-sync", "--disable-extensions"])
    time.sleep(3)
    fake.inject("测试群", "小明", "message while covered")
    time.sleep(2)
    print("covered by 2nd window:", messages(q)[-2:], flush=True)

    q.wake()
    time.sleep(1)
    win32.user32.ShowWindow(q.find_window()[0], 6)           # SW_MINIMIZE
    time.sleep(1)
    fake.inject("测试群", "小明", "message while minimised")
    time.sleep(2)
    print("minimised            :", messages(q), flush=True)
    print("wake ->", q.wake(), flush=True)
    time.sleep(1.5)
    print("after wake           :", messages(q)[-3:], flush=True)
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -match 'qqbot-fake-edge' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"])
    fake.stop()


if __name__ == "__main__":
    main()
