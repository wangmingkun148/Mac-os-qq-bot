"""Small, local touches that make replies read less like a bot.

- ``repeated_patterns``: endings / phrases the account has leaned on in its last few replies, handed to the model as
  ``avoid_repeating`` (a hint, the text is never rewritten here).
- ``split_reply``: a long reply is sent as separate short messages, split at its commas (the commas are dropped), the
  way people in the group type. Done locally, never by the model.
"""
from __future__ import annotations
import re

LEAD_REACTION_CHARS = 3      # "hyw" / "神了" / "？" / "吓哭了" ... before the actual comment
PHRASES = ("是吧", "这下", "属于是", "直接", "神了", "赶紧", "快睡", "重量级")
OPEN, CLOSE = "（(「“《【[", "）)」”》】]"


def repeated_patterns(replies, window=6, threshold=2):
    recent = [str(text or "").strip() for text in list(replies)[-window:]]
    recent = [text for text in recent if text]
    found = []
    if sum(text.endswith(("（", "(")) for text in recent) >= threshold:
        found.append("句尾的半截括号「（」")
    for phrase in PHRASES:
        if sum(phrase in text for text in recent) >= threshold:
            found.append(f"“{phrase}”")
    endings = [re.sub(r"[（(～~。！!？?\s]+$", "", text)[-2:] for text in recent]
    for ending in sorted(set(endings)):
        if len(ending) == 2 and endings.count(ending) >= threshold + 1 and not any(ending in f for f in found):
            found.append(f"以“{ending}”结尾")
    return found


def _paired(text):
    """Indexes of brackets/quotes that have a matching partner (a lone trailing "（" is not a bracket)."""
    stack, inside = [], set()
    for index, ch in enumerate(text):
        if ch in OPEN:
            stack.append((ch, index))
        elif ch in CLOSE:
            want = OPEN[CLOSE.index(ch)]
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][0] == want:
                    inside.update(range(stack[depth][1], index + 1))
                    del stack[depth:]
                    break
    return inside


def split_reply(text, min_chars=12, max_parts=4):
    """Split at top-level commas ("，", and "," that is not a digit separator); [text] when it should stay whole."""
    text = (text or "").strip()
    if min_chars <= 0 or "\n" in text:
        return [text]
    inside = _paired(text)
    parts, start = [], 0
    for index, ch in enumerate(text):
        if index in inside:
            continue
        if ch == "，" or (ch == "," and not (0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit())):
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    parts = [part.strip() for part in parts if part.strip()]
    if len(parts) <= 1:
        return [text]
    if len(text) < min_chars:
        # a short reply stays whole, except a short reaction in front ("hyw，他图啥"), which goes out on its own
        return [parts[0], "，".join(parts[1:])] if len(parts[0]) <= LEAD_REACTION_CHARS else [text]
    if len(parts) > max_parts:
        parts = parts[:max_parts - 1] + ["，".join(parts[max_parts - 1:])]
    return parts


def repeat_chain(history, max_chars=20):
    """The run of identical short texts at the end of a chat: (text, member messages in the run, the bot already joined).
    Pictures without text, stickers, @-mentions and links never count as a repeat."""
    def plain(message):
        # QQ shows a "+1" badge from the third identical message on, and inline emoji are small pictures: both make a text
        # message look like "has an image". A message with text counts as that text; only a picture without text is not one.
        text = " ".join(str(message.get("text", "")).split())
        if (message.get("image_kind") == "sticker" or not text or len(text) > max_chars
                or "@" in text or "http" in text.lower()):
            return None
        return text
    tail = list(history)
    if not tail or plain(tail[-1]) is None:
        return None, [], False
    text, run, joined = plain(tail[-1]), [], False
    for message in reversed(tail):
        if plain(message) != text:
            break
        if message.get("self"):
            joined = True
        elif not message.get("bot"):
            run.append(message)
    return text, list(reversed(run)), joined


_SURVEY = (re.compile(r"你们.*(还是|或者)"), re.compile(r"(更想|更喜欢|更怕|更在意|更能接受|更愿意).*还是"))


def survey_shaped(text):
    """The poll-style two-option question ("你们更怕抽不到还是肝不动") that nearly every proactive topic used to be."""
    return any(pattern.search(text or "") for pattern in _SURVEY)

