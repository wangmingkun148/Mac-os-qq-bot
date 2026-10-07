"""Notes the owner keeps about group members (runtime/people.json, edited in Settings → 群友).

Matched by display name only (QQ shows no stable member id); a person can have several names, so after a rename the
owner adds the new one. Notes are background for the model: never quoted in a reply.
"""
from __future__ import annotations
import json
from pathlib import Path

FIELDS = ("call_as", "about", "notes")
_cache = {}


def _norm(name):
    return " ".join(str(name or "").split())


def load_people(base):
    path = Path(base) / "runtime/people.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return []
    if _cache.get("stamp") != (path, stamp):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            people = [p for p in data.get("people", []) if isinstance(p, dict)]
        except (OSError, json.JSONDecodeError, AttributeError):
            people = []
        _cache.update(stamp=(path, stamp), people=people)
    return _cache["people"]


def people_notes(base, messages, limit=8):
    """Cards of the people who speak in ``messages`` (newest first), only those with something written."""
    index = {}
    for person in load_people(base):
        for name in person.get("names", []):
            if _norm(name):
                index.setdefault(_norm(name), person)
    cards, used = [], set()
    for message in messages:
        if message.get("self") or message.get("bot"):
            continue
        person = index.get(_norm(message.get("sender")))
        if person is None or id(person) in used or not any(str(person.get(k, "")).strip() for k in FIELDS):
            continue
        used.add(id(person))
        cards.append({"name": _norm(message.get("sender")), **{k: str(person.get(k, "")).strip() for k in FIELDS}})
        if len(cards) >= limit:
            break
    return cards
