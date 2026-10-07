"""Starting QQ so that the bot can keep reading it while other windows cover it.

QQ NT is Chromium. Chromium stops updating a window's accessibility tree once another window completely covers it
("native window occlusion"), so the bot would read stale messages. QQ started with the switches below does not do that.
The switches only take effect when QQ is *started* with them; a QQ that is already running needs a restart.
"""
from __future__ import annotations

import base64
import os
import subprocess
import time
from pathlib import Path

from . import uia, win32

QQ_FLAGS = ["--disable-features=CalculateNativeWinOcclusion", "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding"]
MARKER = "CalculateNativeWinOcclusion"
DETACHED = 0x00000008
NEW_PROCESS_GROUP = 0x00000200


def flags_from(config: dict) -> list:
    args = config.get("qq_args")
    return [str(a) for a in args] if isinstance(args, list) else list(QQ_FLAGS)


def find_exe(configured: str = "", process: str = "QQ.exe") -> str:
    if configured and Path(configured).is_file():
        return configured
    for window in uia.top_level_windows(process):
        return window["image"]
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            for sub in ("Tencent\\QQNT\\QQ.exe", "Programs\\Tencent\\QQNT\\QQ.exe", "Tencent\\QQ\\Bin\\QQ.exe"):
                candidate = Path(base) / sub
                if candidate.is_file():
                    return str(candidate)
    return ""


def main_process_pid(process: str = "QQ.exe") -> int:
    """pid of the QQ browser process (the one without --type=...), 0 when QQ is not running."""
    pids = {w["pid"] for w in uia.top_level_windows(process)}
    for pid in pids:
        if "--type=" not in win32.process_command_line(pid):
            return pid
    return next(iter(pids), 0)


def flags_active(process: str = "QQ.exe"):
    """True/False when the running QQ was started with the occlusion switch, None when QQ is not running."""
    pid = main_process_pid(process)
    if not pid:
        return None
    command = win32.process_command_line(pid)
    return MARKER in command if command else None


def start(exe: str, args: list) -> bool:
    try:
        subprocess.Popen([exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=DETACHED | NEW_PROCESS_GROUP, close_fds=True)
        return True
    except OSError:
        return False


def restart(config: dict, process: str = "QQ.exe", wait: float = 25.0) -> dict:
    """Close every QQ process and start QQ again with the switches. The user logs in again if QQ cannot do so itself."""
    exe = find_exe(config.get("qq_app", ""), process)
    if not exe:
        return {"ok": False, "error": "找不到 QQ.exe，请在设置里填写 QQ 程序路径"}
    subprocess.run(["taskkill", "/F", "/T", "/IM", process], capture_output=True, creationflags=win32_no_window())
    time.sleep(1.5)
    if not start(exe, flags_from(config)):
        return {"ok": False, "error": "启动 QQ 失败"}
    end = time.time() + wait
    while time.time() < end:
        if any(w["visible"] for w in uia.top_level_windows(process)):
            return {"ok": True}
        time.sleep(0.5)
    return {"ok": True, "note": "QQ 已启动，等待你登录"}


def win32_no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def make_shortcut(config: dict, process: str = "QQ.exe") -> dict:
    """A desktop shortcut that starts QQ with the switches."""
    exe = find_exe(config.get("qq_app", ""), process)
    if not exe:
        return {"ok": False, "error": "找不到 QQ.exe，请在设置里填写 QQ 程序路径"}
    args = " ".join(f'"{a}"' if " " in a else a for a in flags_from(config))
    script = (
        "$desktop = [Environment]::GetFolderPath('Desktop'); "
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop ('QQ ' + [char]0xFF08 + [char]0x673A + [char]0x5668 + [char]0x4EBA + [char]0x6A21 + [char]0x5F0F + [char]0xFF09 + '.lnk'))); "
        f"$s.TargetPath = '{exe}'; $s.Arguments = '{args}'; $s.IconLocation = '{exe},0'; $s.Description = 'QQ (bot mode)'; $s.Save(); $s.FullName"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", creationflags=win32_no_window())
    if result.returncode != 0:
        return {"ok": False, "error": (result.stderr or "创建快捷方式失败").strip()[:200]}
    return {"ok": True, "path": result.stdout.strip()}
