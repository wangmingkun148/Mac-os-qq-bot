#!/usr/bin/env python3
"""QQ auto-reply backend entry point.

The implementation lives in small modules: ``snapshot`` (read QQ), ``messages`` (archive/tracking),
``llm`` + ``ai_client`` (the AI provider), ``style``/``proactive``/``imaging`` (features), ``engine`` (the
poll/decide/send loop) and ``live_feed`` (status window data).
"""
from __future__ import annotations
import argparse
import fcntl
import json
import sys
from pathlib import Path

import config_check
from engine import Engine, Native
from live_feed import LiveFeed
from llm import Model
from style import backfill_style_history, rebuild_style_profile
import time


def refuse_config(base, errors):
    """Report an unusable config where the app can show it (status/live files), then exit."""
    message = "配置有误，后台没有启动：" + "；".join(errors[:3]) + ("…" if len(errors) > 3 else "")
    print(message, file=sys.stderr)
    status = {"state": "config_error", "message": message, "config_errors": errors,
              "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        (base / "runtime/status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2))
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
        errors, warnings = config_check.check(config_check.apply_defaults(json.loads(args.check_config.read_text())))
        print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False))
        return
    base = args.base.resolve()
    (base / "runtime").mkdir(exist_ok=True)
    config = config_check.apply_defaults(json.loads((base / "config.json").read_text()))
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
    with (base / "runtime/bridge.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        Engine(base, config, Native(), config_warnings=warnings).run()

if __name__ == "__main__":
    main()
