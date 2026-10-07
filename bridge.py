#!/usr/bin/env python3
"""QQ auto-reply backend entry point.

The implementation lives in small modules: ``snapshot`` (read QQ), ``messages`` (archive/tracking),
``llm`` + ``ai_client`` (the AI provider), ``style``/``proactive``/``imaging`` (features), ``engine`` (the
poll/decide/send loop) and ``live_feed`` (status window data).

On Windows the backend runs inside the ``winapp`` process (``python -m winapp``); this module keeps the
command-line helpers (config check, style rebuild) and the shared start-up code.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import config_check
import fsutil
from engine import Engine
from live_feed import LiveFeed
from llm import Model
from procutil import InstanceLock
from style import backfill_style_history, rebuild_style_profile
import time


def load_config(base: Path) -> dict:
    """config.json with defaults applied (UTF-8, tolerating a byte-order mark added by some editors)."""
    return config_check.apply_defaults(json.loads(fsutil.read_json_text(base / "config.json")))


def refuse_config(base, errors):
    """Report an unusable config where the app can show it (status/live files), then exit."""
    message = "配置有误，后台没有启动：" + "；".join(errors[:3]) + ("…" if len(errors) > 3 else "")
    print(message, file=sys.stderr)
    status = {"state": "config_error", "message": message, "config_errors": errors,
              "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        (base / "runtime/status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        feed = LiveFeed(base / "runtime/live.json")
        feed.set_engine(state="config_error", message=message, paused=True)
        feed.flush(force=True)
    except OSError:
        pass
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check-config", type=Path, metavar="FILE",
                        help="validate a config file and print {errors, warnings} as JSON")
    parser.add_argument("--rebuild-style-profile", action="store_true")
    parser.add_argument("--backfill-style-history", action="store_true")
    args = parser.parse_args()
    if args.check_config:
        errors, warnings = config_check.check(config_check.apply_defaults(json.loads(fsutil.read_json_text(args.check_config))))
        print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False))
        return
    base = args.base.resolve()
    (base / "runtime").mkdir(exist_ok=True)
    config = load_config(base)
    errors, warnings = config_check.check(config)
    if errors:
        refuse_config(base, errors)
    if args.rebuild_style_profile:
        state = rebuild_style_profile(base, config, Model(base, config))
        counts = {group: data["summarized_text_messages"] for group, data in state["groups"].items()}
        print(json.dumps({"rebuilt_groups": counts}, ensure_ascii=False))
        return
    if args.backfill_style_history:
        counts = backfill_style_history(base, config, Model(base, config))
        print(json.dumps({"backfilled_groups": counts}, ensure_ascii=False))
        return
    print("This module only offers command-line helpers. Start the Windows app with: python -m winapp", file=sys.stderr)
    sys.exit(1)


def run_engine(base: Path, config: dict, native, warnings=()):
    """Run the reply engine in the calling thread until the native side sends ``shutdown``."""
    lock = InstanceLock(base / "runtime/bridge.lock")
    if not lock.acquire():
        return False
    try:
        Engine(base, config, native, config_warnings=warnings).run()
    finally:
        lock.release()
    return True


if __name__ == "__main__":
    main()
