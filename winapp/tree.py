"""Helpers over the dumped QQ accessibility tree (nested dicts, see ``uia.dump_tree``).

Pure Python, no COM: everything here is unit-testable with a recorded tree. The conversation logic mirrors what
the macOS app did natively (current chat, usable conversation rows, conversation kind)."""
from __future__ import annotations

import re
from typing import Callable, Iterator

MEMBER_COUNT = re.compile(r"^\([0-9]+\)$")


def nodes(node: dict) -> Iterator[dict]:
    """Pre-order walk (iterative: the tree can be 40 levels deep)."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.get("children", ())))


def classes(node: dict) -> set:
    return set(node.get("classes", ()))


def find(node: dict, predicate: Callable[[dict], bool]):
    return next((n for n in nodes(node) if predicate(n)), None)


def find_class(node: dict, name: str):
    return find(node, lambda n: name in n.get("classes", ()))


def find_desc(node: dict, desc: str):
    return find(node, lambda n: n.get("desc") == desc)


def contains(node: dict, target: dict) -> bool:
    return any(n is target for n in nodes(node))


def static_texts(node: dict) -> list:
    return [n.get("value", "") for n in nodes(node) if n.get("role") == "AXStaticText" and n.get("value")]


def annotate(tree: dict) -> dict:
    """Give the message editor the chat title as its description, as the macOS accessibility tree did."""
    editor = find(tree, lambda n: n.get("role") == "AXTextArea")
    header = find_class(tree, "chat-header__contact-name")
    aio = find_class(tree, "aio")
    if editor is not None and header is not None and aio is not None and contains(aio, editor) and contains(aio, header):
        editor["desc"] = header.get("desc", "")
    return tree


# --- conversations -------------------------------------------------------------------------------------------

def conversation_key(title: str, groups) -> str:
    return title if title in groups else "chat:" + title


def conversation_rows(tree: dict, groups, all_conversations: bool) -> list[tuple[str, int, dict]]:
    """(title, index in the list, row node) for every conversation the bot may handle. Titles that occur more
    than once are ambiguous (the key is the display name) and are left out."""
    listing = find_desc(tree, "会话列表")
    if listing is None:
        return []
    rows = []
    for index, row in enumerate(listing.get("children", ())):
        info = find_class(row, "item__info")
        if info is None:
            continue
        label = find(info, lambda n: n.get("role") == "AXStaticText")
        title = (label or {}).get("value", "")
        if title:
            rows.append((title, index, row))
    counts = {}
    for title, _, _ in rows:
        counts[title] = counts.get(title, 0) + 1
    return [item for item in rows if counts[item[0]] == 1 and (all_conversations or item[0] in groups)]


def current_title(tree: dict) -> str:
    editor = find(tree, lambda n: n.get("role") == "AXTextArea")
    aio = find_class(tree, "aio")
    if editor is None or aio is None or not contains(aio, editor):
        return ""
    header = find(aio, lambda n: n.get("role") == "AXButton" and "chat-header__contact-name" in n.get("classes", ()))
    if header is None:
        return ""
    title = header.get("desc", "")
    input_title = editor.get("desc", "")
    if not title or (input_title and input_title != title):
        return ""
    return title


def current_group(tree: dict, groups, all_conversations: bool) -> str:
    title = current_title(tree)
    if not title:
        return ""
    key = conversation_key(title, groups)
    allowed = {conversation_key(t, groups) for t, _, _ in conversation_rows(tree, groups, all_conversations)}
    return key if key in allowed else ""


def conversation_details(tree: dict, groups, all_conversations: bool) -> dict:
    result = {}
    active = current_title(tree)
    for title, _, row in conversation_rows(tree, groups, all_conversations):
        kind = "group" if title in groups else "unknown"
        if find(row, lambda n: n.get("role") == "AXStaticText" and MEMBER_COUNT.match(n.get("value", ""))):
            kind = "group"
        if title == active:
            if find(tree, lambda n: n.get("desc") in ("群成员列表", "群应用")):
                kind = "group"
            elif find_desc(tree, "发起群聊"):
                kind = "private"
        result[conversation_key(title, groups)] = {"title": title, "kind": kind}
    return result


# --- the message editor --------------------------------------------------------------------------------------

def editor_node(tree: dict):
    return find(tree, lambda n: n.get("role") == "AXTextArea")


def draft_text(tree: dict) -> str:
    editor = editor_node(tree)
    return (editor or {}).get("value", "")


def has_image_in_editor(tree: dict) -> bool:
    """A picture (or other attachment) sits in the message box. QQ shows a pasted image as an
    ``editor-el--inline-block`` element, not as an <img> the accessibility tree knows about."""
    editor = editor_node(tree)
    if editor is None:
        return False
    return find(editor, lambda n: n.get("role") == "AXImage" or any(c.startswith("editor-el") for c in n.get("classes", ()))) is not None


def message_images(node: dict) -> Iterator[dict]:
    """Image nodes of a message row, skipping the quoted message of a reply."""
    if "reply-element" in node.get("classes", ()):
        return
    if node.get("role") == "AXImage":
        yield node
    for child in node.get("children", ()):
        yield from message_images(child)


def is_message_id(value: str) -> bool:
    return len(value) >= 10 and value.isdecimal()
