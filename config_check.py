"""Defaults and validation for config.json.

``apply_defaults`` fills the numeric settings the engine indexes directly (so a missing key no longer
crashes a poll with ``KeyError``); ``check`` returns problems: *errors* make the backend refuse to start
or to hot-apply a config, *warnings* are shown in the app (unknown keys with a "did you mean", odd values).
"""
from __future__ import annotations
import difflib
import re

EFFORTS = ("", "minimal", "low", "medium", "high")
NUMBER = (int, float)


class F:
    """One setting: accepted type(s), optional default / range / allowed values."""
    def __init__(self, types, default=None, lo=None, hi=None, choices=None, required=False):
        self.types, self.default, self.lo, self.hi, self.choices, self.required = types, default, lo, hi, choices, required

    def wrong_type(self, value):
        if isinstance(value, bool) and bool not in _tuple(self.types):
            return f"应为 {_name(self.types)}，实际是布尔值"
        if not isinstance(value, _tuple(self.types)):
            return f"应为 {_name(self.types)}，实际是 {type(value).__name__}"
        return None

    def problem(self, value):
        wrong = self.wrong_type(value)
        if wrong:
            return wrong
        if self.choices is not None and value not in self.choices:
            return "只能是 " + " / ".join(repr(c) for c in self.choices if c != "") + ("，或留空" if "" in self.choices else "")
        if isinstance(value, NUMBER) and not isinstance(value, bool):
            if self.lo is not None and value < self.lo:
                return f"不能小于 {self.lo}"
            if self.hi is not None and value > self.hi:
                return f"不能大于 {self.hi}"
        return None


def _tuple(types):
    return types if isinstance(types, tuple) else (types,)


def _name(types):
    names = {str: "文字", bool: "开关(true/false)", int: "整数", float: "数字", list: "列表", dict: "对象", NUMBER: "数字"}
    return "或".join(names.get(t, getattr(t, "__name__", str(t))) for t in ((types,) if types == NUMBER else _tuple(types)))


AI = {
    "name": F(str), "base_url": F(str), "api_key": F(str), "model": F(str), "suffix": F(str),
    "suffix_enabled": F(bool), "reasoning_effort": F(str, choices=EFFORTS), "timeout_seconds": F(NUMBER, lo=1), "timeout_retries": F(int, lo=0, hi=3),
}

SECTIONS = {
    "": {
        "groups": F(list, required=True), "self_names": F(list, required=True),
        "python": F(str), "qq_app": F(str), "qq_args": F(list), "restore_focus": F((bool, str), choices=(True, False, "auto")),"qq_account": F(str), "persona": F(str),
        "poll_seconds": F(NUMBER, 2, lo=0.5), "merge_seconds": F(NUMBER, 6, lo=0), "max_merge_seconds": F(NUMBER, 20, lo=1),
        "cooldown_seconds": F(NUMBER, 12, lo=0), "secondary_max_wait_seconds": F(NUMBER, 8, lo=0),
        "max_merge_waits": F(int, 3, lo=0, hi=50), "retry_failed_batch": F(bool, True),
        "split_reply_min_chars": F(int, 12, lo=0, hi=500), "typing_quiet_seconds": F(NUMBER, lo=0, hi=120),
        "auto_resume_seconds": F(NUMBER, lo=0, hi=3600), "auto_resume_per_hour": F(int, lo=0, hi=60),
        "repeat_follow_probability": F(NUMBER, lo=0, hi=1), "repeat_follow_min": F(int, lo=2, hi=10),
        "style_compress_enabled": F(bool), "style_compress_target_chars": F(int, lo=300, hi=1900),
        "feedback_summary_every": F(int, lo=0, hi=200), "lead_reaction_probability": F(NUMBER, lo=0, hi=1),
        "proactive_smart": F(bool), "proactive_min_hour_share": F(NUMBER, lo=0, hi=1), "proactive_max_idle_seconds": F(NUMBER, lo=0),
        "proactive_min_gap_seconds": F(NUMBER, lo=0), "proactive_backoff_seconds": F(NUMBER, lo=60), "proactive_max_per_day": F(int, lo=0, hi=200),
        "proactive_link_probability": F(NUMBER, lo=0, hi=1), "proactive_candidates": F(int, lo=1, hi=5), "proactive_judge": F(bool),
        "proactive_reaction_seconds": F(NUMBER, lo=60), "proactive_good_reactions": F(int, lo=1),
        "topic_summary_every": F(int, lo=0, hi=200), "topic_summary_max_chars": F(int, lo=100, hi=2000), "feedback_summary_max_chars": F(int, lo=100, hi=2000),
        "image_retention_days": F(int, 7, lo=1, hi=365), "muted_chats": F(list), "context_messages": F(int, 12, lo=1, hi=200),
        "max_reply_chars": F(int, 160, lo=10, hi=2000), "image_max_edge": F(int, lo=0, hi=8192),
        "verify_seconds": F(NUMBER, lo=1), "verify_max_seconds": F(NUMBER, lo=1),
        "wake_seconds": F(NUMBER, lo=1), "wake_seconds_max": F(NUMBER, lo=1),
        "reply_all_conversations": F(bool), "reply_style_group": F(str), "group_context_file": F((str, type(None))),
        "message_archive_file": F(str), "style_sample_messages": F(int, lo=0), "style_summary_every": F(int, lo=10),
        "style_profile_max_chars": F(int, lo=100, hi=1999), "style_summary_max_chars": F(int, lo=100, hi=1999),
        "style_backfill_history": F(bool), "proactive_idle_seconds": F(NUMBER, lo=60),
        "proactive_probability": F(NUMBER, lo=0, hi=1), "proactive_enabled": F(bool),
    },
    "browser": {"enabled": F(bool), "python": F(str)},
    "image_generation": {
        "enabled": F(bool), "endpoint": F(str), "model": F(str), "api_key": F(str), "size": F(str),
        "max_per_24h": F(int, lo=0), "timeout_seconds": F(NUMBER, lo=1), "unlimited_senders": F(list), "usage_file": F(str)},
    "qzone": {"schedule_enabled": F(bool), "hour": F(int, lo=0, hi=23), "interval_seconds": F(NUMBER, lo=10), "timezone": F(str)},
    "live_window": {"auto_show": F(bool)},
    "pet": {"enabled": F(bool), "scale": F(int, lo=1, hi=12), "wander": F(bool), "bubble": F(bool)},
    "proactive_search": {"news_rss": F(bool), "youtube": F(bool), "yt_dlp": F(str)},
    "ai": AI,
}
for _section in [name for name in SECTIONS if name]:
    SECTIONS[""][_section] = F(dict)


def apply_defaults(config: dict) -> dict:
    """Fill missing top-level settings that have a default; returns ``config`` (mutated)."""
    for key, spec in SECTIONS[""].items():
        if spec.default is not None and key not in config:
            config[key] = spec.default
    return config


def _check_section(path, data, spec, errors, warnings):
    label = (path + ".") if path else ""
    for key, value in data.items():
        if key not in spec:
            near = difflib.get_close_matches(key, spec, n=1, cutoff=0.6)
            warnings.append(f"未知设置「{label}{key}」，不会生效" + (f"（是否想写「{label}{near[0]}」？）" if near else ""))
            continue
        field = spec[key]
        problem = field.problem(value)
        if problem:
            # a wrongly typed value the engine indexes directly would crash a poll: refuse it outright
            fatal = (field.required or field.default is not None) and field.wrong_type(value)
            (errors if fatal else warnings).append(f"「{label}{key}」{problem}")
    for key, field in spec.items():
        if field.required and key not in data:
            errors.append(f"缺少必填设置「{label}{key}」")


def check(config: dict):
    """Return (errors, warnings) as lists of readable Chinese sentences."""
    errors, warnings = [], []
    if not isinstance(config, dict):
        return ["config.json 不是一个 JSON 对象"], []
    for path, spec in SECTIONS.items():
        data = config if path == "" else config.get(path)
        if data is None:
            continue
        if not isinstance(data, dict):
            warnings.append(f"「{path}」应为对象")
            continue
        _check_section(path, data, spec, errors, warnings)
    groups = config.get("groups")
    if isinstance(groups, list) and (not groups or not all(isinstance(g, str) and g.strip() and g != "填写主群完整名称" for g in groups)):
        errors.append("「groups」至少要有一个群名，且每项都是非空文字")
    if isinstance(config.get("self_names"), list) and (not config["self_names"] or not all(isinstance(n, str) and n.strip() and n != "填写本账号昵称" for n in config["self_names"])):
        errors.append("「self_names」不能为空：程序靠它确认当前登录的是哪个 QQ 账号")
    if isinstance(config.get("max_merge_seconds"), NUMBER) and isinstance(config.get("merge_seconds"), NUMBER) \
            and config["max_merge_seconds"] < config["merge_seconds"]:
        warnings.append("「max_merge_seconds」小于「merge_seconds」，合并等待会以较小者为准")
    ai = config.get("ai") if isinstance(config.get("ai"), dict) else {}
    missing = [label for key, label in (("base_url", "接口地址"), ("api_key", "API Key"), ("model", "模型名称")) if not str(ai.get(key) or "").strip()]
    if missing:
        warnings.append("AI 供应商还没填完整（缺少：" + "、".join(missing) + "）：请在设置 → AI 供应商里填写，否则无法回复")
    elif not re.match(r"https?://", str(ai.get("base_url"))):
        warnings.append("「ai.base_url」应以 http:// 或 https:// 开头")
    return errors, warnings
