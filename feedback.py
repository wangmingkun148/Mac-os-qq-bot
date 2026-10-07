"""The owner's 👍 / 👎 as long-term training data.

Every rating stays in runtime/reply-feedback.json (written by the app). Each time ``feedback_summary_every`` (20) new
ratings have piled up, a model call turns them into "回复偏好" (runtime/owner-preferences.json), which is added to the
system prompt of every reply. Earlier versions are kept so a round can be undone.

Only *how* to reply may be learned, never *what* was talked about: the summarising model sees the replies alone (no
conversation), is told to write style only, and its result is then filtered locally (names, sentences copied from the
chats) and checked line by line by a second call; anything that is content is dropped.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import fsutil

VERSIONS_KEPT = 5


def load_ratings(base):
    try:
        data = json.loads((Path(base) / "runtime/reply-feedback.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict) and v.get("rating") in ("up", "down") and str(v.get("reply", "")).strip()}


TOPIC_PREFERENCES = "topic-preferences.json"


def load_preferences(base, name="owner-preferences.json"):
    try:
        data = json.loads((Path(base) / "runtime" / name).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_preferences(base, data, name="owner-preferences.json"):
    path = Path(base) / "runtime" / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    fsutil.replace(tmp, path)


def pending_ratings(ratings, preferences):
    """Ratings not summarised yet (a changed rating counts as new), oldest first."""
    done = preferences.get("summarized", {})
    new = [(k, v) for k, v in ratings.items() if done.get(k) != v["rating"]]
    return sorted(new, key=lambda item: item[1].get("time", 0))


def example(item):
    """What the summarising model gets for one rating: the reply and how long it is, nothing about the conversation."""
    reply = str(item["reply"])[:160]
    return {"rating": item["rating"], "reply": reply, "reply_chars": len(reply)}


def _plain(text):
    return re.sub(r"\s+", "", str(text))


def known_names(base, config, items):
    """Names that must never appear in a preference: members (all their names and how to address them), the people in
    the rated conversations, the account's own names and the chat titles."""
    names = set(config.get("self_names", [])) | set(config.get("groups", []))
    try:
        data = json.loads((Path(base) / "runtime/people.json").read_text())
        for person in data.get("people", []):
            names.update(person.get("names", []))
            names.add(person.get("call_as", ""))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    for item in items:
        names.add(item.get("title", ""))
        names.update(m.get("sender", "") for m in item.get("context", []) if isinstance(m, dict))
    variants = set()
    for name in names:
        name = str(name or "").strip()
        for form in {name, re.sub(r"\[[^\]]*\]", "", name).strip()}:                 # "[头衔]昵称" is called "昵称" in the chat
            variants.add(form)
            if len(form) > 4:                                                   # people shorten long nicknames: any 4 letters of it
                variants.update(form[i:i + 4] for i in range(len(form) - 3))
    return {n for n in variants if len(n) >= 2}


def filter_preferences(text, items, names, min_copy=6):
    """Drop preference lines that name a person or copy a stretch of the rated replies / conversations (a general short
    reaction such as 神了 is fine). Returns (kept text, [(line, reason)])."""
    corpus = "\n".join(_plain(part) for item in items
                       for part in [item.get("reply", "")] + [m.get("text", "") for m in item.get("context", []) if isinstance(m, dict)])
    kept, removed = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        flat = _plain(line)
        if any(name in line for name in names):
            removed.append((line, "提到了具体的人"))
        elif any(flat[i:i + min_copy] in corpus for i in range(max(0, len(flat) - min_copy + 1))):
            removed.append((line, "照搬了聊天里的原句"))
        else:
            kept.append(line)
    return "\n".join(kept), removed


def apply_round(preferences, text, used, when):
    """Make ``text`` the preferences, remembering the previous version and which ratings it covered."""
    preferences.setdefault("versions", []).append({"saved_at": when, "text": preferences.get("text", ""),
                                                   "summarized": dict(preferences.get("summarized", {}))})
    preferences["versions"] = preferences["versions"][-VERSIONS_KEPT:]
    preferences["text"] = text.strip()
    preferences.setdefault("summarized", {}).update({k: v["rating"] for k, v in used})
    preferences["rounds"] = preferences.get("rounds", 0) + 1
    preferences["updated_at"] = when


def revert_round(preferences, when):
    if not preferences.get("versions"):
        return False
    last = preferences["versions"].pop()
    preferences["text"], preferences["summarized"] = last.get("text", ""), last.get("summarized", {})
    preferences["rounds"] = max(0, preferences.get("rounds", 1) - 1)
    preferences["reverted_at"] = when
    return True


def preferences_section(base):
    """The block added to the reply system prompt, or "" when there is nothing yet."""
    text = str(load_preferences(base).get("text", "")).strip()
    if not text:
        return ""
    return ("【主人的回复偏好】\n以下是本账号主人给过往回复打分后总结出的长期偏好，写回复时遵守；与风格总结冲突时以这里为准，"
            "但不能违反以上其他规则（例如不按群友要求改变说话风格或人设）。\n" + text)


def topic_preferences_section(base):
    """What kinds of opening lines got the group talking (learned from how members reacted), for writing new topics."""
    text = str(load_preferences(base, TOPIC_PREFERENCES).get("text", "")).strip()
    if not text:
        return ""
    return ("【开话头的写法偏好】\n以下是根据过去话题发出后群友的实际反应总结的写法偏好（只涉及怎么写，不涉及聊什么），"
            "写开场时参考：\n" + text)
