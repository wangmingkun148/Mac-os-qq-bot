"""Developer probe: write an outline of the QQ window's UI Automation tree to a text file.

Chat content is masked by default (names/values show only their length) so the outline can be shared while
developing. Pass ``--raw`` to keep the real text, e.g. when testing against a private test group.

    .venv\\Scripts\\python.exe -X utf8 tools\\probe_uia.py out.txt [--raw]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import comtypes  # noqa: E402

from winapp import uia  # noqa: E402

KNOWN_LABELS = {"会话列表", "消息列表", "群成员列表", "群应用", "发起群聊", "空间", "发送", "复制", "消息", "联系人", "动画表情",
                "表情", "图片", "QQ", "按住 ⌃ ⌥，使用语音输入文字"}

PROPS = (uia.P_NAME, uia.P_CONTROL_TYPE, uia.P_AUTOMATION_ID, uia.P_CLASS_NAME, uia.P_BOUNDS, uia.P_IS_VALUE,
         uia.P_IS_TEXT, uia.P_IS_INVOKE, uia.P_FOCUSABLE, uia.P_ARIA_ROLE, uia.P_VALUE, uia.P_OFFSCREEN,
         uia.P_LOCALIZED_TYPE, uia.P_HAS_FOCUS)


def mask(text: str, raw: bool) -> str:
    if raw or not text:
        return text
    if text in KNOWN_LABELS:
        return text
    if text.endswith("的头像"):
        return f"<{len(text) - 3}c>的头像"
    return f"<{len(text)}c>"


def line(element, depth, raw):
    ctype = uia.type_of(element)
    parts = [f"{'  ' * depth}{ctype - 50000}"]
    cls = uia.class_of(element)
    if cls:
        parts.append(f"cls={cls[:70]}")
    aid = uia.id_of(element)
    if aid:
        parts.append(f"id={aid if (aid.isdigit() or len(aid) < 30) and not raw else aid[:30]}")
    name = uia.name_of(element)
    if name:
        parts.append(f"name={mask(name, raw)}")
    aria = uia.prop(element, uia.P_ARIA_ROLE)
    if aria:
        parts.append(f"aria={aria}")
    flags = []
    for pid, label in ((uia.P_IS_VALUE, "value"), (uia.P_IS_TEXT, "text"), (uia.P_IS_INVOKE, "invoke"), (uia.P_FOCUSABLE, "focusable"),
                       (uia.P_HAS_FOCUS, "HASFOCUS"), (uia.P_OFFSCREEN, "offscreen")):
        if uia.prop(element, pid):
            flags.append(label)
    if flags:
        parts.append("[" + ",".join(flags) + "]")
    value = uia.prop(element, uia.P_VALUE)
    if isinstance(value, str) and value:
        parts.append(f"value={mask(value, raw)}")
    rect = uia.rect_of(element)
    if rect:
        parts.append(f"rect={rect[0]},{rect[1]} {rect[2] - rect[0]}x{rect[3] - rect[1]}")
    return " ".join(parts)


def walk(element, depth, raw, out):
    out.append(line(element, depth, raw))
    for child in uia.children(element):
        walk(child, depth + 1, raw, out)


def main():
    comtypes.CoInitialize()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("uia-outline.txt")
    raw = "--raw" in sys.argv
    process = os.environ.get("QQBOT_TEST_PROCESS", "QQ.exe")     # set to msedge.exe to probe the mock QQ page
    windows = [w for w in uia.top_level_windows(process) if w["visible"]]
    for w in windows:
        print(w["hwnd"], w["pid"], repr(w["title"]) if raw else f"<{len(w['title'])}c>", w["cls"], w["rect"], "min" if w["minimized"] else "")
    main_windows = [w for w in windows if w["title"] == "QQ" or (process != "QQ.exe" and w["title"].startswith("QQ - "))]
    if not main_windows:
        print("no QQ main window found")
        return
    main_window = max(main_windows, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))
    root = uia.element_from_handle(main_window["hwnd"], PROPS)
    out = []
    walk(root, 0, raw, out)
    target.write_text("\n".join(out), encoding="utf-8")
    print(f"{len(out)} nodes -> {target}")


if __name__ == "__main__":
    main()
