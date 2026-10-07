"""Group speaking-style samples, long-term style summaries and group context."""
from __future__ import annotations
import collections
import json
import os
import time
from messages import MessageArchive, is_style_message
import fsutil


def tail_group_records(path, group, limit, block=1 << 16):
    """The last ``limit`` archive records of ``group`` in file order, read from the end of the file so the
    cost does not grow with the archive. Unparseable lines are skipped."""
    found = []
    try:
        with path.open("rb") as handle:
            position = handle.seek(0, os.SEEK_END)
            carry = b""
            while position > 0 and len(found) < limit:
                step = min(block, position)
                position -= step
                handle.seek(position)
                pieces = (handle.read(step) + carry).split(b"\n")
                carry, complete = (pieces[0], pieces[1:]) if position > 0 else (b"", pieces)
                for raw in reversed(complete):
                    try:
                        record = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and record.get("group") == group:
                        found.append(record)
                        if len(found) >= limit:
                            break
    except OSError:
        pass
    found.reverse()
    return found


def load_style_examples(base, config, group, recent):
    limit = config.get("style_sample_messages", 36)
    if limit <= 0:
        return []
    path = base / config.get("message_archive_file", "runtime/messages.jsonl")
    records = collections.deque(tail_group_records(path, group, 600), maxlen=600)
    records.extend({"group": group, **message} for message in recent)
    selected, seen, per_sender = [], set(), collections.Counter()
    for record in reversed(records):
        ident = str(record.get("id", ""))
        text = str(record.get("text", "")).strip()
        sender = str(record.get("sender", "")).strip()
        if not ident or ident in seen or record.get("self") or record.get("bot") or not sender or not text or record.get("image_kind") == "sticker":
            continue
        if len(text) > 180 or not any(char.isalnum() for char in text) or per_sender[sender] >= 8:
            continue
        seen.add(ident)
        per_sender[sender] += 1
        selected.append({"sender": sender, "text": text})
        if len(selected) >= limit:
            break
    return list(reversed(selected))


def extend_style_summary(previous, additions, other="", max_chars=1999):
    limit = max(0, min(max_chars, 1999) - len(other.strip()) - (2 if other.strip() else 0))
    summary = previous.strip()[:limit]
    known = other + "\n" + summary
    for line in additions.splitlines():
        line = line.strip()
        if not line or line in known:
            continue
        candidate = (summary + "\n" + line).strip()
        if len(candidate) <= limit:
            summary = candidate
            known += "\n" + line
    return summary


def load_style_profile(base, group, max_chars=1999):
    try:
        state = json.loads((base / "runtime/style-profile.json").read_text(encoding="utf-8"))
        entry = state.get("groups", {}).get(group, {})
        pieces = [entry.get("historical_summary", ""), entry.get("summary", "")]
        return "\n\n".join(piece.strip() for piece in pieces if isinstance(piece, str) and piece.strip())[:min(max_chars, 1999)]
    except (OSError, json.JSONDecodeError):
        return ""


def reply_profile_fields(base, config, group):
    source = config.get("reply_style_group") or next(iter(config.get("groups", [])), group)
    limit = config.get("style_profile_max_chars", 1999)
    return {
        "style_profile": load_style_profile(base, source, limit),
        "style_profile_source": source,
        "conversation_memory": load_style_profile(base, group, limit) if group != source else "",
    }


_history_cache = {}


def archived_style_messages(path, group):
    """Every style-eligible text message of ``group`` in archive order (callers must not modify the list).
    Results are reused until the archive file changes."""
    try:
        stat = path.stat()
    except OSError:
        return []
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _history_cache.get((str(path), group))
    if cached and cached[0] == stamp:
        return cached[1]
    result = []
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("group") == group and is_style_message(record):
                    result.append({"sender": str(record.get("sender", "")), "text": str(record["text"]).strip()})
    except OSError:
        return []
    if len(_history_cache) >= 8:
        _history_cache.clear()
    _history_cache[(str(path), group)] = (stamp, result)
    return result


def load_group_context(base, config, group=None):
    """只提供群聊约定和话术记忆，不传入运行记录或技术操作说明。"""
    if group is not None and group not in config["groups"]:
        return ""
    path = config.get("group_context_file")
    if not path:
        return ""
    try:
        text = (base / path).read_text(encoding="utf-8")
    except OSError:
        return ""
    start = text.find("## 一、")
    end = text.find("## 七、")
    return text[max(start, 0):end if end >= 0 else len(text)].strip()


def rebuild_style_profile(base, config, model):
    batch_size = config.get("style_summary_every", 100)
    archive = MessageArchive(base / config.get("message_archive_file", "runtime/messages.jsonl"))
    state = {"groups": {}}
    for group in config["groups"]:
        messages = archived_style_messages(archive.path, group)
        summary = ""
        for start in range(0, len(messages), batch_size):
            batch = messages[start:start + batch_size]
            result = model.summarize_style(group, summary, batch)
            summary = result["summary"]
            state["groups"][group] = {
                "summarized_text_messages": start + len(batch), "summary": summary,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "backend": result["backend"], "model": result["model"],
                "reasoning_effort": result["reasoning_effort"],
            }
            target = base / "runtime/style-profile.json"
            tmp = base / "runtime/style-profile.rebuild.tmp"
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(tmp, 0o600)
            fsutil.replace(tmp, target)
        if messages:
            state["groups"][group] = {
                "summarized_text_messages": len(messages), "summary": summary,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "backend": result["backend"], "model": result["model"],
                "reasoning_effort": result["reasoning_effort"],
            }
    return state


def backfill_style_history(base, config, model):
    target = base / "runtime/style-profile.json"
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"groups": {}}
    batch_size = config.get("style_summary_every", 100)
    archive = MessageArchive(base / config.get("message_archive_file", "runtime/messages.jsonl"))
    completed = {}
    for group in config["groups"]:
        entry = state.setdefault("groups", {}).setdefault(group, {})
        messages = archived_style_messages(archive.path, group)
        recent_count = entry.get("summarized_text_messages", 0)
        history_end = max(recent_count - batch_size, 0)
        if history_end <= 0:
            continue
        summary = ""
        for start in range(0, history_end, batch_size):
            batch = messages[start:min(start + batch_size, history_end)]
            result = model.summarize_style(group, summary, batch, other_summary=entry.get("summary", ""))
            summary = result["summary"]
            entry["historical_summary"] = summary
            entry["historical_summarized_text_messages"] = start + len(batch)
            entry["historical_updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            tmp = base / "runtime/style-profile.backfill.tmp"
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            os.chmod(tmp, 0o600)
            fsutil.replace(tmp, target)
        completed[group] = history_end
    return completed


# -- compressing a full style summary ---------------------------------------------------------------------------
VERSIONS_KEPT = 5


def style_limit(config):
    return min(config.get("style_profile_max_chars", 1999), config.get("style_summary_max_chars", 1999), 1999)


def style_length(entry):
    parts = [str(entry.get(k, "")).strip() for k in ("historical_summary", "summary")]
    return sum(len(p) for p in parts) + (2 if all(parts) else 0)


def compress_samples(path, group, count=800):
    """Recent real member messages the compression is checked against (text only, no names)."""
    return [m["text"][:80] for m in archived_style_messages(path, group)[-count:]]


def measured_style(path, group, count=3000):
    """Facts counted from real messages, so the compression labels frequencies from data instead of impressions."""
    texts = [m["text"].strip() for m in archived_style_messages(path, group)[-count:] if m["text"].strip()]
    if not texts:
        return {}
    n = len(texts)
    share = lambda hits: f"{round(100 * hits / n)}%"
    lengths = sorted(len(t) for t in texts)
    short = collections.Counter(t for t in texts if len(t) <= 4)
    return {
        "消息条数": n,
        "长度中位数（字）": lengths[n // 2],
        "4 字以内的消息占比": share(sum(l <= 4 for l in lengths)),
        "20 字以上的消息占比": share(sum(l >= 20 for l in lengths)),
        "以半截括号“（”或“(”结尾的占比": share(sum(t.endswith(("（", "(")) for t in texts)),
        "含成对空括号“（）”的占比": share(sum("（）" in t or "()" in t for t in texts)),
        "以问号结尾的占比": share(sum(t.endswith(("?", "？")) for t in texts)),
        "以句号结尾的占比": share(sum(t.endswith(("。", ".")) for t in texts)),
        "以感叹号结尾的占比": share(sum(t.endswith(("!", "！")) for t in texts)),
        "最常见的短消息（次数）": [f"{t}（{c}）" for t, c in short.most_common(20)],
    }


def apply_compression(entry, result, when):
    """Keep the previous version (newest last, at most VERSIONS_KEPT) and make the compressed text the whole summary."""
    entry.setdefault("versions", []).append({"saved_at": when, "historical_summary": entry.get("historical_summary", ""),
                                             "summary": entry.get("summary", "")})
    entry["versions"] = entry["versions"][-VERSIONS_KEPT:]
    entry["historical_summary"] = result["summary"]
    entry["summary"] = ""
    entry["compressed_at"] = when
    entry["compress_dropped"] = list(result.get("dropped", []))


def revert_compression(entry, when):
    """Back to the version before the last compression (traits added since then are dropped). False if none."""
    if not entry.get("versions"):
        return False
    last = entry["versions"].pop()
    entry["historical_summary"], entry["summary"] = last.get("historical_summary", ""), last.get("summary", "")
    entry["reverted_at"] = when
    entry.pop("compressed_at", None)
    entry.pop("compress_dropped", None)
    return True

