"""Entry point:  python -X utf8 -m winapp [--base DIR] [--start] [--console] [--dry-run]"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path


def ensure_utf8_mode():
    """The backend writes Chinese text with Python's default encoding; make that UTF-8 regardless of the system
    code page (GBK on Chinese Windows). Re-launches once with ``-X utf8`` when needed."""
    if sys.flags.utf8_mode or getattr(sys, "frozen", False):
        return
    env = dict(os.environ, PYTHONUTF8="1")
    sys.exit(subprocess.call([sys.executable, "-X", "utf8", "-m", "winapp", *sys.argv[1:]], env=env))


def default_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def main(argv=None):
    ensure_utf8_mode()
    parser = argparse.ArgumentParser(prog="winapp")
    parser.add_argument("--base", type=Path, default=default_base(), help="project folder (holds config.json and runtime/)")
    parser.add_argument("--start", action="store_true", help="start replying as soon as the app is up")
    parser.add_argument("--console", action="store_true", help="no tray icon or windows; print status to the console")
    parser.add_argument("--dry-run", action="store_true", help="read QQ but never click, type or send anything")
    parser.add_argument("--show", choices=("popover", "live", "settings"), help="open one window on launch")
    args = parser.parse_args(argv)

    from . import win32
    win32.set_dpi_aware()
    from .app import App

    app = App(args.base, dry_run=args.dry_run)
    problem = app.prepare_project()
    if problem:
        print(problem, file=sys.stderr)
        return 1

    if args.console:
        return run_console(app, args)

    from .shell import run_shell
    return run_shell(app, args)


def run_console(app, args) -> int:
    last = {"text": None}

    def changed():
        if app.status_text != last["text"]:
            last["text"] = app.status_text
            print(time.strftime("%H:%M:%S"), app.status_text, flush=True)

    app.on_state_change = changed
    app.notify_sink = lambda title, body: print(f"[通知] {title}: {body}", flush=True)
    app.ensure_native()
    app.start_backend()
    if args.start:
        app.toggle()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
