"""Message records: archive, new-message tracking and who a message is addressed to."""
from __future__ import annotations
import collections
import json
import os
import re
import time


def is_style_message(record):
    text = str(record.get("text", "")).strip()
    return bool(record.get("group") and not record.get("self") and not record.get("bot") and record.get("image_kind") != "sticker" and
                text and len(text) <= 180 and any(char.isalnum() for char in text))


def addressed_to_self(message, config):
    if message.get("self") or message.get("bot"):
        return False
    text = str(message.get("text", ""))
    return any(re.search(rf"(?<![A-Za-z0-9._-])@{re.escape(name)}(?=$|[\s，,。.!！?？：:；;])", text)
               for name in config.get("self_names", []))


def image_generation_request(message, config):
    """只接受明确 @ 本账号的直接生图指令，能力询问不触发调用。"""
    text = str(message.get("text", "")).strip()
    if not text or not addressed_to_self(message, config):
        return None
    names = config.get("self_names", [])
    without_mentions = text
    for name in names:
        without_mentions = re.sub(rf"@{re.escape(name)}(?=$|[\s，,。.!！?？：:；;])", " ", without_mentions)
    request = " ".join(without_mentions.split()).strip()
    if re.search(r"(?:能不能|能否|会不会|可以不可以|是否可以|能画|会画).{0,8}(?:图|画|图片)", request):
        return None
    command = re.search(r"(?:请|麻烦|帮我|给我|帮忙)?\s*(?:生成|画|绘制|做|制作)(?:一张|一幅|一个|个)?(?:图片|图|画|头像|壁纸|海报|表情包)?", request)
    if not command:
        return None
    prompt = request[command.start():].strip(" ，,。.!！?？")
    return prompt[:1200] if prompt else None


class MessageArchive:
    def __init__(self, path):
        self.path = path
        self.recent = collections.defaultdict(lambda: collections.deque(maxlen=80))
        self.ids = collections.defaultdict(set)
        self.text_counts = collections.Counter()
        self.member_messages_since_reply = collections.Counter()
        try:
            self.count = 0
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    self.count += 1
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get("group") and record.get("id"):
                        self.ids[record["group"]].add(record["id"])
                        self.recent[record["group"]].append(record)
                    if is_style_message(record):
                        self.text_counts[record["group"]] += 1
                    self._count_reply_gap(record)
        except OSError:
            self.count = 0

    def _count_reply_gap(self, record):
        group = record.get("group")
        if not group or record.get("bot"):
            return
        if record.get("self"):
            self.member_messages_since_reply[group] = 0
        elif str(record.get("text", "")).strip() and any(c.isalnum() for c in str(record["text"])):
            self.member_messages_since_reply[group] += 1

    def append(self, group, message):
        record = {"received_at": time.strftime("%Y-%m-%d %H:%M:%S"), "group": group, **message}
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            os.chmod(self.path, 0o600)
            self.count += 1
            self.ids[group].add(message["id"])
            self.recent[group].append(record)
            if is_style_message(record):
                self.text_counts[group] += 1
            self._count_reply_gap(record)
        except OSError:
            pass


class Tracker:
    def __init__(self, archive=None):
        self.initialized = set()
        self.seen = collections.defaultdict(set)
        self.history = collections.defaultdict(lambda: collections.deque(maxlen=80))
        self.pending = collections.defaultdict(list)
        self.first = {}
        self.last = {}
        self.waits = {}                      # merge-wait periods started for the current pending batch
        self.last_member_activity = {}
        self.archive = archive
        if archive:
            for group, records in getattr(archive, "recent", {}).items():
                self.history[group].extend(records)
            for group, ids in getattr(archive, "ids", {}).items():
                self.seen[group].update(ids)

    def ingest(self, group, messages, now, initial_new_count=0, max_waits=0):
        """``max_waits`` caps how many times new messages may restart the merge timer of a pending batch
        (the first message starts wait 1); 0 = no cap, the timer restarts on every message."""
        tail_ids = {m["id"] for m in messages[-initial_new_count:]} if initial_new_count else set()
        baseline = group not in self.initialized and not initial_new_count
        fresh = [m for m in messages if m["id"] not in self.seen[group] and
                 (baseline or not m.get("content_pending"))]
        for message in fresh:
            self.seen[group].add(message["id"])
            self.history[group].append(message)
        if group not in self.initialized:
            self.initialized.add(group)
            self.last_member_activity[group] = now
            if not initial_new_count:
                return []
            # On first opening a newly changed chat, only the new tail triggers replies.
            fresh = [m for m in fresh if m["id"] in tail_ids]
        if any(not message["self"] and not message.get("bot") for message in fresh):
            self.last_member_activity[group] = now
        if self.archive:
            for message in fresh:
                self.archive.append(group, message)
        fresh = [m for m in fresh if not m["self"] and not m.get("bot") and m.get("image_kind") != "sticker" and
                 (m.get("has_image") or (m["text"] and any(c.isalnum() for c in m["text"]))) ]
        if fresh:
            if not self.pending[group]:
                self.first[group] = now
                self.waits[group] = 1
                self.last[group] = now
            elif not max_waits or self.waits.get(group, 1) < max_waits:
                self.waits[group] = self.waits.get(group, 1) + 1
                self.last[group] = now
            self.pending[group].extend(fresh)
        return fresh

    def due(self, group, now, config):
        return bool(self.pending[group]) and (
            now - self.last[group] >= config["merge_seconds"] or
            now - self.first[group] >= config["max_merge_seconds"])
