"""Step-by-step live test of the automation against the REAL QQ, restricted to one test group.

    .venv\\Scripts\\python.exe -X utf8 tools\\live_qq_test.py <group> check|send|image|capture|draft|wake|all

Everything that sends or types goes only into <group>; each operation re-checks that the open chat is exactly that
group first. Chat text is not printed, apart from the test strings this script sends itself.
It takes over the keyboard and mouse for a few seconds per step: do not type while it runs.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import comtypes  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from snapshot import parse_snapshot  # noqa: E402
from winapp import qqlaunch, tree as T, win32  # noqa: E402
from winapp.qq import QQ  # noqa: E402


class Shell:
    paused = False
    pending_send = False

    def __init__(self, group, me):
        self.config = {"groups": [group], "self_names": [me], "reply_all_conversations": False, "typing_quiet_seconds": 1.0}
        self.base = tempfile.mkdtemp(prefix="qqbot-live-")
        (Path(self.base) / "runtime").mkdir()
        self.watcher = win32.TypingWatcher()
        self.watcher.start()

    def typing_seconds(self):
        return self.watcher.seconds_since_typing()

    def nativelog(self, line):
        print("   [native]", line, flush=True)


def me_from(tree):
    return next((n["desc"][:-3] for n in T.nodes(tree) if n.get("role") == "AXButton" and n.get("desc", "").endswith("的头像")), "")


def read_me(probe, attempts=12):
    """Nickname of the logged-in account from the top bar; the tree can be incomplete right after QQ was restored."""
    for _ in range(attempts):
        tree = probe.read_tree()
        if not isinstance(tree, str):
            name = me_from(tree)
            if name:
                return name
        time.sleep(1.0)
    return ""


def messages(q, shell):
    snap = q.snapshot()
    if "error" in snap:
        return None, snap["error"]
    return parse_snapshot(snap, shell.config), None


def report(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
    return ok


def ensure_open(q, group):
    """Make sure the test group is the open chat; True when it is."""
    for _ in range(3):
        view = q.good_view()
        if view is not None and view.title() == group and view.editor_node is not None:
            return True
        print("   select ->", q.select(group), flush=True)
        time.sleep(1.5)
    view = q.good_view()
    return view is not None and view.title() == group


def stage_check(q, shell, group):
    report("QQ main window found", bool(q.find_window()))
    view = q.view()
    if isinstance(view, str):
        return report("window readable", False, view)
    tree = view.tree
    rows = [t for t, _, _ in T.conversation_rows(tree, [group], True)]
    report("test group is in the conversation list (unique)", group in rows)
    report("open chat", True, "the test group" if view.title() == group else "another chat (will switch)")
    report("message editor found", view.editor() is not None, "draft empty" if not view.draft_present() else "draft present!")
    report("send button found", view.send_button() is not None)
    report("QQ started with the occlusion switch", bool(qqlaunch.flags_active()), "if False: QQ is not readable while covered")
    parsed, err = messages(q, shell)
    if parsed is not None and parsed["group"] == group:
        mine = sum(1 for m in parsed["messages"] if m["self"])
        report("messages parsed in the test group", True, f"{len(parsed['messages'])} visible, {mine} mine, "
                                                                 f"{sum(1 for m in parsed['messages'] if m['has_image'])} with images")
    return True


def stage_send(q, shell, group):
    if not ensure_open(q, group):
        return report("test group open", False)
    marker = f"自动回复测试 {time.strftime('%H:%M:%S')}"
    before = {m["id"] for m in messages(q, shell)[0]["messages"]}
    result = q.send(group, marker)
    report("send returned submitted", bool(result.get("submitted")), str(result))
    time.sleep(1.5)
    parsed, err = messages(q, shell)
    new = [m for m in (parsed or {"messages": []})["messages"] if m["id"] not in before and m["self"]]
    report("sent text read back as my own new message", any(marker in m["text"] for m in new), f"{len(new)} new self messages")
    view = q.good_view()
    report("editor empty afterwards", view is not None and not view.draft_present())


def make_png(path, text):
    image = Image.new("RGB", (360, 200), (30, 120, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 349, 189), outline=(255, 255, 255), width=3)
    draw.text((30, 80), text, fill=(255, 255, 255))
    image.save(path)


def stage_image(q, shell, group):
    if not ensure_open(q, group):
        return report("test group open", False)
    path = Path(shell.base) / "runtime" / "generated-livetest.png"
    make_png(path, "BOT IMAGE TEST " + time.strftime("%H:%M:%S"))
    before = {m["id"] for m in messages(q, shell)[0]["messages"]}
    started = time.time()
    result = q.send_image(group, "", str(path))
    report("send_image returned ok", bool(result.get("ok")), f"{result} in {time.time() - started:.1f}s")
    time.sleep(2)
    parsed, _ = messages(q, shell)
    new = [m for m in (parsed or {"messages": []})["messages"] if m["id"] not in before and m["self"] and m["has_image"]]
    report("image read back as my own new image message", bool(new))


def stage_capture(q, shell, group):
    if not ensure_open(q, group):
        return report("test group open", False)
    parsed, _ = messages(q, shell)
    images = [m for m in parsed["messages"] if m["has_image"] and m["image_kind"] != "sticker"]
    if not images:
        return report("there is an image message to copy", False, "send one first (stage image)")
    target = images[-1]
    started = time.time()
    result = q.capture_image(group, message_id=target["id"])
    ok = bool(result.get("path")) and Path(result["path"]).is_file()
    report("capture_image copied the picture (right-click > copy)", ok, f"{ {k: v for k, v in result.items() if k != 'path'} } in {time.time() - started:.1f}s")
    if ok:
        with Image.open(result["path"]) as img:
            report("captured file is a valid image", img.size[0] > 20, f"{img.size}")
        print("   saved:", result["path"], flush=True)


def stage_draft(q, shell, group):
    if not ensure_open(q, group):
        return report("test group open", False)
    view = q.good_view()
    if view is None or view.editor() is None or view.draft_present():
        return report("editor is empty before the test", False)
    q.activate()
    time.sleep(0.5)
    view = q.good_view()
    q.focus_editor(view.editor())
    time.sleep(0.2)
    win32.type_text("草稿测试 draft")
    time.sleep(0.5)
    view = q.good_view()
    typed = view.draft().strip()
    report("typed text arrived in the editor", typed == "草稿测试 draft", repr(typed))
    result = q.clear_draft(group, "草稿测试 draft")
    report("clear_draft removed it", bool(result.get("ok")), str(result))
    view = q.good_view()
    report("editor empty again", view is not None and not view.draft_present())
    # a draft that is not ours must be refused
    q.activate()
    time.sleep(0.3)
    view = q.good_view()
    q.focus_editor(view.editor())
    win32.type_text("别人的草稿")
    time.sleep(0.4)
    refused = q.clear_draft(group, "不是这个内容")
    report("clear_draft refuses a different draft", refused.get("error") == "draft_differs", str(refused))
    view = q.good_view()
    q.focus_editor(view.editor())
    win32.press_key(win32.VK_A, win32.VK_CONTROL)
    time.sleep(0.1)
    win32.press_key(win32.VK_BACK)
    time.sleep(0.3)
    view = q.good_view()
    report("cleaned up my own test text", view is not None and not view.draft_present())


def stage_wake(q, shell, group):
    hwnd = q.find_window()[0]
    win32.user32.ShowWindow(hwnd, 6)                       # minimise the main window
    time.sleep(1.2)
    snap = q.snapshot()
    report("minimised QQ reports qq_window_missing", snap.get("error") == "qq_window_missing", str(snap.get("error")))
    result = q.wake()
    time.sleep(1.5)
    after = q.find_window()
    view = q.good_view()
    report("wake restores the MAIN window (not a hidden one)", bool(result.get("ok")) and after is not None and after[0] == hwnd
           and not win32.user32.IsIconic(hwnd) and view is not None and view.editor() is not None, str(result))
    others = [w for w in q.main_windows(visible_only=True) if w["hwnd"] != hwnd and not w["minimized"]]
    report("no stray QQ window was shown", not others, f"{len(others)} other visible windows")


def main():
    group = sys.argv[1]
    stages = sys.argv[2:] or ["check"]
    win32.set_dpi_aware()
    comtypes.CoInitialize()
    probe = QQ(type("S", (), {"config": {}, "paused": False, "pending_send": False, "base": ".", "typing_seconds": lambda self: 99, "nativelog": lambda self, l: None})())
    me = read_me(probe)
    if not me:
        print("QQ window not readable (no account nickname found)")
        return 1
    shell = Shell(group, me)
    q = QQ(shell)
    q.read_tree()
    time.sleep(0.5)
    table = {"check": stage_check, "send": stage_send, "image": stage_image, "capture": stage_capture, "draft": stage_draft, "wake": stage_wake}
    order = ["check", "send", "image", "capture", "draft", "wake"] if "all" in stages else stages
    for name in order:
        print(f"--- {name} ---", flush=True)
        table[name](q, shell, group)
    return 0


if __name__ == "__main__":
    sys.exit(main())
