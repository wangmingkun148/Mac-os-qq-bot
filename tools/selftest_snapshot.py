"""Developer self-test: read the live QQ window and run it through the backend's snapshot parser.

Prints only counts and flags (no chat text). Uses the chat that is currently open as the "main group" and the
logged-in nickname from the top bar, so it needs no config.

    .venv\\Scripts\\python.exe -X utf8 tools\\selftest_snapshot.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import comtypes  # noqa: E402

from snapshot import parse_snapshot  # noqa: E402
from winapp import tree as T  # noqa: E402
from winapp import uia  # noqa: E402


def main():
    comtypes.CoInitialize()
    windows = [w for w in uia.top_level_windows() if w["visible"] and w["title"] == "QQ"]
    if not windows:
        print("QQ main window not found")
        return 1
    window = max(windows, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))
    started = time.perf_counter()
    root = uia.element_from_handle(window["hwnd"], uia.DUMP_PROPS)
    tree = T.annotate(uia.dump_tree(root))
    dump_ms = (time.perf_counter() - started) * 1000
    me = next((n["desc"][:-3] for n in T.nodes(tree) if n.get("role") == "AXButton" and n.get("desc", "").endswith("的头像")), "")
    title = T.current_title(tree)
    config = {"groups": [title] if title else [], "self_names": [me], "reply_all_conversations": False}
    snapshot = {"tree": tree, "activeConversation": T.current_group(tree, config["groups"], False),
                "conversationDetails": T.conversation_details(tree, config["groups"], True)}
    parsed = parse_snapshot(snapshot, config)
    print(f"dump {dump_ms:.0f} ms, nodes={sum(1 for _ in T.nodes(tree))}")
    print("self nickname found:", bool(me), "| active chat title found:", bool(title))
    if parsed.get("error"):
        print("parse error:", parsed["error"])
        return 1
    print("group is the open chat:", parsed["group"] == title, "| messages_ready:", parsed["messages_ready"])
    print("sidebar conversations parsed:", len(T.conversation_rows(tree, config["groups"], True)))
    print("draft length:", len(parsed["draft"]))
    for message in parsed["messages"][-12:]:
        print(f"  id={message['id']} self={message['self']} bot={message['bot']} image={message['has_image']}"
              f"({message['image_kind'] or '-'}) pending={message['content_pending']} sender_len={len(message['sender'])}"
              f" text_len={len(message['text'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
