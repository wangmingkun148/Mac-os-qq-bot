"""Reading and driving the QQ NT desktop window (Windows).

This is the Windows counterpart of the macOS app's ``BridgeAutomation.swift``: every public method answers one
operation of the backend protocol (``snapshot``, ``select``, ``send`` ...) with the same result shape and error
codes, so the Python engine does not need to know which platform it runs on.

All methods must be called from the worker thread that initialised COM (see ``winapp.worker``).
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from PIL import Image

from . import clipboard, tree as T, uia, win32
from .uia import UIA

NAV_MESSAGES = "消息"
CONTROL_IMAGE, CONTROL_MENUITEM = 50006, 50011


def squash(text: str) -> str:
    return "".join(str(text).split())


class QQ:
    def __init__(self, shell):
        self.shell = shell              # provides: config, paused, pending_send, typing_seconds(), nativelog(), base
        self._hwnd = 0
        self._pid = 0
        # development only: drive the mock QQ page (tools/fake_qq) running in Edge instead of the real client
        self.process = os.environ.get("QQBOT_TEST_PROCESS", "QQ.exe")

    # ------------------------------------------------------------------ plumbing
    @property
    def config(self):
        return self.shell.config

    @property
    def groups(self):
        return self.config.get("groups", [])

    @property
    def all_conversations(self) -> bool:
        return bool(self.config.get("reply_all_conversations"))

    def log(self, line: str):
        self.shell.nativelog(line)

    def user_typing(self) -> bool:
        quiet = self.config.get("typing_quiet_seconds", 3)
        return self.shell.typing_seconds() < float(quiet if isinstance(quiet, (int, float)) else 3)

    # ------------------------------------------------------------------ windows / processes
    def title_ok(self, title: str) -> bool:
        return title == "QQ" or (self.process != "QQ.exe" and title.startswith("QQ - "))

    def main_windows(self, visible_only=True):
        windows = [w for w in uia.top_level_windows(self.process)
                   if self.title_ok(w["title"]) and w["cls"] == "Chrome_WidgetWin_1"]
        if visible_only:
            windows = [w for w in windows if w["visible"]]
        return windows

    def find_window(self, allow_minimized=False):
        """(hwnd, pid) of the QQ main window, or None. Hidden windows never count; minimised ones only on request."""
        if self._hwnd and win32.is_window(self._hwnd) and self.title_ok(uia.window_title(self._hwnd)) \
                and win32.user32.IsWindowVisible(self._hwnd) and (allow_minimized or not win32.user32.IsIconic(self._hwnd)):
            return self._hwnd, self._pid
        candidates = [w for w in self.main_windows() if allow_minimized or not w["minimized"]]
        if not candidates:
            self._hwnd = self._pid = 0
            return None
        best = max(candidates, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))
        self._hwnd, self._pid = best["hwnd"], best["pid"]
        return self._hwnd, self._pid

    def qq_running(self) -> bool:
        return bool(uia.top_level_windows(self.process))

    def qq_executable(self, configured: str = "") -> str:
        """Path of QQ.exe: the configured one, the running process, or the usual install locations."""
        if configured and Path(configured).is_file():
            return configured
        for window in uia.top_level_windows(self.process):
            return window["image"]
        for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                for sub in ("Tencent\\QQNT\\QQ.exe", "Programs\\Tencent\\QQNT\\QQ.exe", "Tencent\\QQ\\Bin\\QQ.exe"):
                    candidate = Path(base) / sub
                    if candidate.is_file():
                        return str(candidate)
        return ""

    def launch(self, app: str = "") -> dict:
        """Start QQ when it has no usable window (QQ is single-instance, so this also shows a tray-hidden window)."""
        if self.main_windows(visible_only=True):
            return {"ok": True, "already": True}
        path = self.qq_executable(app)
        if not path:
            return {"error": "qq_executable_not_found"}
        try:
            os.startfile(path)  # noqa: S606  (ShellExecute, like double-clicking the shortcut)
        except OSError as exc:
            return {"error": f"qq_launch_failed: {exc}"}
        return {"ok": True}

    def wake(self) -> dict:
        if self.user_typing():
            return {"error": "user_typing"}
        windows = self.main_windows(visible_only=False)
        if not windows:
            return {"error": "qq_not_running"}
        window = max(windows, key=lambda w: (w["rect"][2] - w["rect"][0]) * (w["rect"][3] - w["rect"][1]))
        self._hwnd, self._pid = window["hwnd"], window["pid"]
        win32.bring_to_front(window["hwnd"])
        return {"ok": True}

    def activate(self) -> bool:
        found = self.find_window(allow_minimized=True)
        return bool(found) and win32.bring_to_front(found[0])

    def foreground_ok(self) -> bool:
        return bool(self._pid) and win32.foreground_is(self._pid)

    # ------------------------------------------------------------------ reading
    def live_root(self):
        found = self.find_window()
        if not found:
            return None
        try:
            return uia.automation().ElementFromHandle(found[0])
        except Exception:
            return None

    def read_tree(self):
        """Annotated tree dict of the window, or an error string."""
        found = self.find_window()
        if not found:
            return "qq_window_missing"
        try:
            root = uia.element_from_handle(found[0], uia.DUMP_PROPS)
        except Exception:
            return "qq_content_unavailable"
        tree = uia.dump_tree(root)
        if not tree.get("children"):
            return "qq_content_unavailable"
        return T.annotate(tree)

    def snapshot(self) -> dict:
        tree = self.read_tree()
        if isinstance(tree, str):
            return {"error": tree}
        groups, allconv = self.groups, self.all_conversations
        return {
            "tree": tree,
            "activeConversation": T.current_group(tree, groups, allconv),
            "paused": self.shell.paused,
            "pid": self._pid,
            "conversationDetails": T.conversation_details(tree, groups, allconv),
            "idleSeconds": min(self.shell.typing_seconds(), 1e6),
        }

    # live element lookups ------------------------------------------------------------------------------------
    def editor_element(self, root):
        holder = uia.find_first(root, cls="qq-msg-editor__root")
        if holder is None:
            return None
        kids = uia.live_children(holder)
        return kids[0] if kids else None

    def editor_text(self, editor) -> str:
        try:
            if "is-empty" in (editor.CurrentClassName or "").split():
                return ""
        except Exception:
            pass
        return uia.pattern_text(editor)

    def editor_empty(self, editor) -> bool:
        return not self.editor_text(editor).strip()

    def editor_has_image(self, editor) -> bool:
        return bool(uia.find_all(editor, ctype=CONTROL_IMAGE))

    def draft_present(self, editor) -> bool:
        return not self.editor_empty(editor) or self.editor_has_image(editor)

    def title_live(self, root) -> str:
        header = uia.find_first(root, cls="chat-header__contact-name")
        return uia.name_of(header, cached=False) if header is not None else ""

    def group_live(self, root) -> str:
        """Key of the open chat (fast check without dumping the tree): title when configured, else ``chat:title``."""
        title = self.title_live(root)
        if not title:
            return ""
        key = T.conversation_key(title, self.groups)
        return key if (title in self.groups or self.all_conversations) else ""

    def group_checked(self) -> str:
        """Key of the open chat, verified against the unique, visible conversation rows (slow path)."""
        tree = self.read_tree()
        if isinstance(tree, str):
            return ""
        return T.current_group(tree, self.groups, self.all_conversations)

    def row_rect(self, element):
        rect = uia.rect_of(element, cached=False)
        return rect if rect and rect[2] > rect[0] and rect[3] > rect[1] else None

    def click_element(self, element, at: str = "center") -> bool:
        rect = self.row_rect(element)
        if not rect:
            return False
        x = (rect[0] + rect[2]) // 2
        y = (rect[1] + rect[3]) // 2
        if at == "caret":          # near the bottom-right of an input box, where the text caret goes
            x, y = rect[0] + max(12, rect[2] - rect[0] - 24), rect[1] + max(12, rect[3] - rect[1] - 24)
        win32.click(x, y)
        return True

    # ------------------------------------------------------------------ select
    def select(self, name: str, force: bool = False) -> dict:
        if (self.shell.paused and not force) or self.shell.pending_send:
            return {"error": "paused_or_group_not_allowed"}
        tree = self.read_tree()
        if isinstance(tree, str):
            return {"error": tree}
        rows = T.conversation_rows(tree, self.groups, self.all_conversations)
        keys = {T.conversation_key(title, self.groups): (index, row) for title, index, row in rows}
        if name not in keys:
            return {"error": "conversation_not_allowed"}
        if T.editor_node(tree) is not None and T.current_group(tree, self.groups, self.all_conversations) == name:
            return {"ok": True}
        editor = T.editor_node(tree)
        if editor is not None and (editor.get("value", "").strip() or T.has_image_in_editor(tree)):
            return {"error": "draft_present"}
        root = self.live_root()
        if root is None:
            return {"error": "qq_window_missing"}
        listing = uia.find_first(root, name="会话列表")
        if listing is None:
            tab = uia.find_first(root, name=NAV_MESSAGES, ctype=50000)
            if tab is not None:
                return {"ok": uia.invoke(tab) or self.click_element(tab)}
            return {"error": "open_qq_messages_tab"}
        index = keys[name][0]
        rows_live = uia.live_children(listing)
        if index >= len(rows_live):
            return {"error": "group_not_in_visible_list"}
        row = rows_live[index]
        if uia.invoke(row):
            return {"ok": True}
        if uia.is_offscreen(row):
            uia.scroll_into_view(row)
            time.sleep(0.2)
        if self.click_element(row):
            return {"ok": True}
        return {"error": "group_press_unsupported"}

    # ------------------------------------------------------------------ image capture
    def capture_image(self, group: str, message_id: str = "", latest: bool = False, exclude=()) -> dict:
        if self.shell.paused or self.shell.pending_send or not group:
            return {"error": "image_context_changed"}
        root = self.live_root()
        if root is None or self.group_live(root) != group:
            return {"error": "image_context_changed"}
        mid = message_id
        if latest:
            excluded = set(exclude)
            tree = self.read_tree()
            if isinstance(tree, str):
                return {"error": "image_context_changed"}
            listing = T.find_desc(tree, "消息列表")
            candidates = []
            for item in T.nodes(listing or {}):
                dom = item.get("domId", "")
                if T.is_message_id(dom) and dom not in excluded and "ml-item" in item.get("classes", ()):
                    own = T.find(item, lambda n: bool({"message-container--self", "container--self"} & set(n.get("classes", ()))))
                    if own is None and next(T.message_images(item), None) is not None:
                        candidates.append(dom)
            if not candidates:
                return {"error": "no_new_image"}
            mid = candidates[-1]
        if not T.is_message_id(mid):
            return {"error": "image_unavailable"}
        row = uia.find_first(root, cls="ml-item", aid=mid)
        if row is None:
            return {"error": "image_unavailable"}
        picture = self.row_picture(row)
        if picture is None:
            return {"error": "image_unavailable"}
        if self.user_typing():
            return {"error": "user_active_or_draft_present"}
        editor = self.editor_element(root)
        if editor is None or self.draft_present(editor):
            return {"error": "user_active_or_draft_present"}
        if not self.bring_into_view(root, row, picture):
            return {"error": "image_not_visible"}
        rect = self.row_rect(picture)
        if not rect or rect[2] - rect[0] <= 10 or rect[3] - rect[1] <= 10:
            return {"error": "image_not_visible"}
        previous = clipboard.save()
        initial = clipboard.sequence_number()
        self.shell.pending_send = True
        try:
            if not self.activate():
                return {"error": "image_context_changed"}
            time.sleep(0.2)
            root = self.live_root()
            row = uia.find_first(root, cls="ml-item", aid=mid) if root is not None else None
            picture = self.row_picture(row) if row is not None else None
            if (self.shell.paused or not self.foreground_ok() or root is None or self.group_live(root) != group
                    or picture is None):
                return {"error": "image_context_changed"}
            rect = self.row_rect(picture)
            if not rect:
                return {"error": "image_not_visible"}
            win32.click((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2, right=True)
            item = None
            for _ in range(12):                    # the menu reaches the accessibility tree a moment after it appears
                time.sleep(0.15)
                item = self.find_menu_item(root, "复制")
                if item is not None:
                    break
            if item is None:
                win32.press_key(win32.VK_ESCAPE)
                self.log("image copy: no 复制 menu item found after right-click")
                return {"error": "image_copy_unavailable"}
            if not (uia.invoke(item) or self.click_element(item)):
                win32.press_key(win32.VK_ESCAPE)
                return {"error": "image_copy_unavailable"}
            image = None
            changed = initial
            for _ in range(10):
                time.sleep(0.2)
                changed = clipboard.sequence_number()
                if changed == initial:
                    continue
                try:
                    image = clipboard.read_image()
                except OSError:
                    image = None
                if image is not None:
                    break
            if changed == initial:
                self.log(f"image copy: clipboard never changed (sequence {initial}); open by: {clipboard.busy_owner() or 'nobody'}; "
                         f"formats now: {clipboard.formats()}")
                return {"error": "image_copy_timeout"}
            if image is None:
                return {"error": "image_clipboard_unreadable", "types": ",".join(clipboard.formats())[:250]}
            return self.save_capture(image, mid)
        finally:
            if clipboard.sequence_number() != initial:
                clipboard.restore(previous)
            self.shell.pending_send = False

    def bring_into_view(self, root, row, picture) -> bool:
        """Make the centre of ``picture`` visible inside the message list (UIA reports a half-hidden element as
        on screen, and a click on the hidden half would hit the input box or toolbar)."""
        view = self.row_rect(uia.find_first(root, name="消息列表") or picture)
        for attempt in range(8):
            rect = self.row_rect(picture)
            if rect and view:
                cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
                if view[0] < cx < view[2] and view[1] + 8 < cy < view[3] - 8 and not uia.is_offscreen(picture):
                    return True
                if attempt == 0:
                    uia.scroll_into_view(row)
                    time.sleep(0.25)
                    continue
                below = cy >= view[3] - 8
                win32.scroll_wheel((view[0] + view[2]) // 2, (view[1] + view[3]) // 2, -3 if below else 3)
                time.sleep(0.3)
            else:
                return False
        return False

    def row_picture(self, row):
        """The photo/sticker element of a message row (never the quoted picture inside a reply)."""
        for image in uia.find_all(row, ctype=CONTROL_IMAGE):
            if uia.name_of(image, cached=False) in ("图片", "动画表情", "表情") or "pic-element" in uia.class_of(image, cached=False):
                return image
        return None

    def find_menu_item(self, root, label: str):
        """The context-menu entry ``label``: searched in the QQ window first, then in every top-level QQ window."""
        item = uia.find_first(root, name=label, ctype=CONTROL_MENUITEM)
        if item is not None:
            return item
        for window in uia.top_level_windows(self.process):
            if window["visible"] and window["hwnd"] != self._hwnd:
                try:
                    top = uia.automation().ElementFromHandle(window["hwnd"])
                except Exception:
                    continue
                item = uia.find_first(top, name=label)
                if item is not None:
                    return item
        return uia.find_first(root, name=label)

    def save_capture(self, image: Image.Image, message_id: str) -> dict:
        path = Path(self.shell.base) / "runtime" / f"image-{uuid.uuid4()}.jpg"
        try:
            image = image.convert("RGB")
            image.save(path, "JPEG", quality=85)
        except Exception:
            return {"error": "image_save_failed"}
        if path.stat().st_size >= 25_000_000:
            path.unlink(missing_ok=True)
            return {"error": "image_clipboard_unreadable", "types": "too large"}
        return {"path": str(path), "message_id": message_id}

    # ------------------------------------------------------------------ sending
    def focus_editor(self, editor) -> bool:
        uia.set_focus(editor)
        time.sleep(0.05)
        if uia.has_focus(editor):
            return True
        return self.click_element(editor, at="caret")

    def press_send(self, root, editor) -> bool:
        button = uia.find_first(root, cls="send-msg")
        if button is not None and uia.invoke(button):
            return True
        return False

    def clear_editor(self):
        """Select everything in the (focused) message box and delete it."""
        win32.press_key(win32.VK_A, win32.VK_CONTROL)
        time.sleep(0.05)
        win32.press_key(win32.VK_BACK)

    def send(self, group: str, text: str) -> dict:
        shell = self.shell
        if shell.paused or shell.pending_send or not group or not text or "\n" in text:
            return {"error": "send_not_allowed"}
        root = self.live_root()
        if root is None:
            return {"error": "qq_window_missing"}
        editor = self.editor_element(root)
        if editor is None:
            return {"error": "editor_unavailable"}
        actual = self.group_live(root)
        if actual != group:
            return {"error": "wrong_conversation", "actual_group": actual}
        if self.draft_present(editor):
            return {"error": "draft_present"}
        if self.user_typing():
            return {"error": "user_typing"}
        shell.pending_send = True
        stage = "prepare"                      # prepare -> typed (text is in the box) -> submitted (may be on its way)
        try:
            if not self.activate():
                return {"error": "activation_or_draft_changed"}
            time.sleep(0.35)
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if (shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group
                    or self.draft_present(editor)):
                return {"error": "activation_or_draft_changed"}
            if not self.focus_editor(editor):
                return {"error": "focus_changed"}
            time.sleep(0.15)
            if shell.paused or not self.foreground_ok() or not uia.has_focus(editor):
                return {"error": "focus_changed"}
            stage = "typed"
            win32.type_text(text)
            time.sleep(0.25)
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if (shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group
                    or self.editor_text(editor).strip() != text.strip()):
                self.discard_own_draft(group, text)
                return {"error": "focus_or_draft_changed"}
            self.focus_editor(editor)
            stage = "submitted"                # from here on the message may be on its way: never clear, never resend
            if not self.press_send(root, editor):
                win32.press_key(win32.VK_RETURN)
            time.sleep(0.6)
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if root is None or editor is None or self.group_live(root) != group:
                return {"submitted": True, "awaiting_readback": True}
            if self.editor_empty(editor):
                return {"ok": True, "submitted": True}
            return {"error": "text_still_in_editor"}
        except Exception as exc:
            self.log(f"send failed at stage {stage}: {type(exc).__name__}: {exc}")
            if stage == "submitted":
                return {"error": "text_send_context_changed"}
            if stage == "typed":
                self.discard_own_draft(group, text)
            return {"error": "send_not_allowed"}
        finally:
            shell.pending_send = False

    def discard_own_draft(self, group: str, text: str):
        """Remove what a failed send typed, but only while the box still holds our own text."""
        try:
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if editor is None or self.group_live(root) != group:
                return
            current = squash(self.editor_text(editor))
            if current and squash(text).startswith(current) and self.foreground_ok():
                self.focus_editor(editor)
                self.clear_editor()
                self.log("cleared the partial text a failed send left in the message box")
        except Exception as exc:  # best effort
            self.log(f"could not clear partial text: {exc}")

    def clear_draft(self, group: str, expected: str) -> dict:
        if self.user_typing():
            return {"error": "user_typing"}
        if self.shell.pending_send or not expected:
            return {"error": "editor_unavailable"}
        root = self.live_root()
        editor = self.editor_element(root) if root is not None else None
        if editor is None:
            return {"error": "editor_unavailable"}
        if self.group_live(root) != group:
            return {"error": "wrong_conversation"}
        if squash(self.editor_text(editor)) != squash(expected):
            return {"error": "draft_differs"}
        if not self.activate():
            return {"error": "clear_failed"}
        time.sleep(0.3)
        root = self.live_root()
        editor = self.editor_element(root) if root is not None else None
        if editor is None or not self.focus_editor(editor):
            return {"error": "clear_failed"}
        if squash(self.editor_text(editor)) != squash(expected):
            return {"error": "draft_differs"}
        self.clear_editor()
        time.sleep(0.3)
        root = self.live_root()
        editor = self.editor_element(root) if root is not None else None
        if editor is None or not self.editor_empty(editor):
            return {"error": "clear_failed"}
        self.log("cleared the bot's stuck draft after an uncertain send")
        return {"ok": True}

    def send_image(self, group: str, text: str, path: str) -> dict:
        shell = self.shell
        runtime = (Path(shell.base) / "runtime").resolve()
        try:
            file = Path(path).resolve()
        except OSError:
            return {"error": "image_send_not_allowed"}
        if (shell.paused or shell.pending_send or not group or len(text) > 120 or runtime not in file.parents
                or file.suffix.lower() not in (".png", ".jpg", ".jpeg") or not file.is_file()):
            return {"error": "image_send_not_allowed"}
        root = self.live_root()
        editor = self.editor_element(root) if root is not None else None
        if editor is None or self.group_live(root) != group:
            return {"error": "wrong_conversation"}
        if self.draft_present(editor):
            self.log("send_image refused: message box not empty")
            return {"error": "draft_present"}
        if self.user_typing():
            return {"error": "user_typing"}
        previous = clipboard.save()
        image_sequence = None
        stage = "prepare"                      # prepare -> pasted (picture may be in the box) -> submitted
        shell.pending_send = True
        self.log(f"send_image start: text={text} file={file.name}")

        def finish(result):
            if image_sequence is not None and clipboard.sequence_number() == image_sequence:
                clipboard.restore(previous)
            shell.pending_send = False
            return result

        try:
            if not self.activate():
                return finish({"error": "activation_or_draft_changed"})
            time.sleep(0.35)
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if (shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group
                    or self.draft_present(editor)):
                return finish({"error": "activation_or_draft_changed"})
            self.focus_editor(editor)
            time.sleep(0.2)
            if shell.paused or not self.foreground_ok() or self.group_live(root) != group:
                return finish({"error": "image_focus_changed"})
            # a bare "@name" leaves QQ's mention suggestion open, which swallows Return; a trailing space closes it
            typed = text + " " if text.startswith("@") and not text.endswith(" ") else text
            if typed:
                win32.type_text(typed)
                time.sleep(0.2)
            try:
                if not clipboard.set_image(file):
                    return finish({"error": "image_clipboard_write_failed"})
            except OSError:
                return finish({"error": "image_clipboard_write_failed"})
            image_sequence = clipboard.sequence_number()
            stage = "pasted"
            win32.press_key(win32.VK_V, win32.VK_CONTROL)
            time.sleep(5.0)                    # QQ needs a few seconds to take the picture
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group:
                return finish({"error": "image_paste_context_changed"})
            self.focus_editor(editor)
            time.sleep(0.25)
            root = self.live_root()
            editor = self.editor_element(root) if root is not None else None
            if shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group:
                return finish({"error": "image_send_context_changed"})
            if not self.editor_has_image(editor):
                self.log("send_image: no picture appeared in the message box after pasting")
                self.discard_own_draft(group, typed)
                return finish({"error": "image_paste_not_ready"})
            newlines_before = self.editor_text(editor).count("\n")
            stage = "submitted"
            sent = self.press_send(root, editor)
            if not sent:
                win32.press_key(win32.VK_RETURN)
            for attempt in (1, 2, 3):
                time.sleep(3.0)
                root = self.live_root()
                editor = self.editor_element(root) if root is not None else None
                if shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group:
                    return finish({"error": "image_send_context_changed"})
                if not self.draft_present(editor):
                    method = ("click" if sent else "return") if attempt == 1 else "return+retry"
                    self.log(f"send_image done: attempt {attempt}, {method}")
                    return finish({"ok": True, "submitted": True, "method": method})
                added = self.editor_text(editor).count("\n") - newlines_before
                self.log(f"send_image attempt {attempt} did not send")
                if added > 0:
                    for _ in range(min(added, 10)):
                        win32.press_key(win32.VK_BACK)
                if attempt == 3:
                    return finish({"error": "image_newline_instead_of_send" if added > 0 else "image_still_in_editor"})
                time.sleep(4.0)
                root = self.live_root()
                editor = self.editor_element(root) if root is not None else None
                if shell.paused or editor is None or not self.foreground_ok() or self.group_live(root) != group:
                    return finish({"error": "image_send_context_changed"})
                self.focus_editor(editor)
                time.sleep(0.25)
                if not self.press_send(root, editor):
                    win32.press_key(win32.VK_RETURN)
            return finish({"error": "image_still_in_editor"})
        except Exception as exc:
            self.log(f"send_image failed at stage {stage}: {type(exc).__name__}: {exc}")
            return finish({"error": {"submitted": "image_send_context_changed", "pasted": "image_still_in_editor"}
                           .get(stage, "image_send_not_allowed")})
