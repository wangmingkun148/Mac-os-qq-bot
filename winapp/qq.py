"""Reading and driving the QQ NT desktop window (Windows).

This is the Windows counterpart of the macOS app's ``BridgeAutomation.swift``: every public method answers one
operation of the backend protocol (``snapshot``, ``select``, ``send`` ...) with the same result shape and error
codes, so the Python engine does not need to know which platform it runs on.

Elements are located through a *view*: one cached read of the whole window (about 60 ms) that yields the dumped tree
and the live UIA element behind every node. Live ``FindFirst`` cannot be used for this: it only searches UIA's
control view, which leaves out the generic containers QQ's layout is made of (``aio``, ``ml-item``,
``qq-msg-editor__root``). Views are cheap, so every step of an operation takes a fresh one instead of trusting
elements that may have gone stale.

All methods must be called from the worker thread that initialised COM (see ``winapp.native``).
"""
from __future__ import annotations

import os
import time
import uuid
from pathlib import Path

from PIL import Image

from . import clipboard, qqlaunch, tree as T, uia, win32

NAV_MESSAGES = "消息"
PICTURE_NAMES = ("图片", "动画表情", "表情")


def squash(text: str) -> str:
    return "".join(str(text).split())


class View:
    """One read of the QQ window: the dumped tree plus the live UIA element behind every node."""

    def __init__(self, tree: dict, elements: list, config: dict):
        self.tree = tree
        self.elements = elements
        self.groups = config.get("groups", [])
        self.all_conversations = bool(config.get("reply_all_conversations"))
        self.editor_node = T.editor_node(tree)

    def element(self, node):
        index = None if node is None else node.get("_i")
        return None if index is None else self.elements[index]

    # the message box
    def editor(self):
        return self.element(self.editor_node)

    def draft(self) -> str:
        return (self.editor_node or {}).get("value", "")

    def has_image(self) -> bool:
        return T.has_image_in_editor(self.tree)

    def draft_present(self) -> bool:
        return bool(self.draft().strip()) or self.has_image()

    # the open chat
    def title(self) -> str:
        header = T.find_class(self.tree, "chat-header__contact-name")
        return (header or {}).get("desc", "")

    def group(self) -> str:
        """Key of the open chat: its title when configured (or ``chat:title`` when every chat is handled)."""
        if self.editor_node is None:
            return ""
        title = self.title()
        if not title or not (title in self.groups or self.all_conversations):
            return ""
        return T.conversation_key(title, self.groups)

    def send_button(self):
        return self.element(T.find_class(self.tree, "send-msg"))

    def message_list(self):
        return T.find_desc(self.tree, "消息列表")

    # messages
    def row(self, message_id: str):
        return T.find(self.tree, lambda n: n.get("domId") == message_id and "ml-item" in n.get("classes", ()))

    def picture(self, row_node):
        """The photo/sticker of a message row (never the quoted picture inside a reply)."""
        for image in T.message_images(row_node or {}):
            if image.get("desc") in PICTURE_NAMES or "pic-element" in image.get("classes", ()):
                return image
        return None


class QQ:
    def __init__(self, shell):
        self.shell = shell              # provides: config, paused, pending_send, typing_seconds(), nativelog(), base
        self._hwnd = 0
        self._pid = 0
        # development only: drive the mock QQ page (tools/fake_qq) running in Edge instead of the real client
        self.process = os.environ.get("QQBOT_TEST_PROCESS", "QQ.exe")
        self._previous = 0
        self._flags_checked = -1e9
        self._flags_ok = False

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

    def has_conversation_list(self, hwnd) -> bool:
        """Is this QQ window the main window (the one with the conversation list)? QQ keeps several windows titled
        "QQ" (hidden login/splash windows among them), so the title alone does not identify it."""
        try:
            return uia.find_first(uia.automation().ElementFromHandle(hwnd), name="会话列表") is not None
        except Exception:
            return False

    def find_window(self, allow_minimized=False):
        """(hwnd, pid) of the QQ main window, or None. Hidden windows never count; minimised ones only on request.
        Once found, the main window is remembered, also while it is minimised."""
        if self._hwnd and win32.is_window(self._hwnd) and self.title_ok(uia.window_title(self._hwnd)) \
                and win32.user32.IsWindowVisible(self._hwnd) and (allow_minimized or not win32.user32.IsIconic(self._hwnd)):
            return self._hwnd, self._pid
        candidates = [w for w in self.main_windows() if allow_minimized or not w["minimized"]]
        if not candidates:
            if not (self._hwnd and win32.is_window(self._hwnd)):
                self._hwnd = self._pid = 0
            return None
        candidates.sort(key=lambda w: (w["normal"][2] - w["normal"][0]) * (w["normal"][3] - w["normal"][1]), reverse=True)
        best = next((w for w in candidates if not w["minimized"] and self.has_conversation_list(w["hwnd"])), None)
        if best is None and len(candidates) == 1:
            best = candidates[0]
        if best is None:
            # no visible window shows the conversation list: a minimised main window (identified earlier) or nothing
            best = next((w for w in candidates if w["hwnd"] == self._hwnd), None)
        if best is None:
            return None
        self._hwnd, self._pid = best["hwnd"], best["pid"]
        return self._hwnd, self._pid

    def qq_running(self) -> bool:
        return bool(uia.top_level_windows(self.process))

    def qq_executable(self, configured: str = "") -> str:
        """Path of QQ.exe: the configured one, the running process, or the usual install locations."""
        return qqlaunch.find_exe(configured, self.process)

    def launch(self, app: str = "") -> dict:
        """Start QQ when it has no usable window (QQ is single-instance, so this also shows a tray-hidden window).
        A fresh start carries the switches that keep QQ readable while it is covered by other windows."""
        if self.main_windows(visible_only=True):
            return {"ok": True, "already": True}
        path = self.qq_executable(app)
        if not path:
            return {"error": "qq_executable_not_found"}
        if not qqlaunch.start(path, qqlaunch.flags_from(self.config)):
            return {"error": "qq_launch_failed"}
        return {"ok": True}

    def wake(self) -> dict:
        """Bring the QQ main window to the front (restoring it when minimised). A main window that QQ has hidden in
        the tray cannot be told apart from QQ's other hidden "QQ" windows, so it is not forced to show: ``launch``
        (starting QQ.exe again) is what makes a running QQ show it."""
        if self.user_typing():
            return {"error": "user_typing"}
        if not self.qq_running():
            return {"error": "qq_not_running"}
        found = self.find_window(allow_minimized=True)
        if not found:
            return {"error": "qq_hidden"}
        win32.bring_to_front(found[0])
        return {"ok": True}

    def activate(self) -> bool:
        found = self.find_window(allow_minimized=True)
        if not found:
            return False
        current = win32.foreground_hwnd()
        if current and current != found[0] and win32.window_pid(current) != found[1]:
            self._previous = current                  # what the user was looking at: put it back when we are done
        return win32.bring_to_front(found[0])

    def restore_enabled(self) -> bool:
        """Give the focus back to the window the user was in? Only safe when QQ keeps updating while covered."""
        setting = self.config.get("restore_focus", "auto")
        if setting in (True, False):
            return bool(setting)
        now = time.monotonic()
        if now - self._flags_checked > 30:
            self._flags_checked = now
            self._flags_ok = bool(qqlaunch.flags_active(self.process))
        return self._flags_ok

    def finish_focus(self):
        previous, self._previous = self._previous, 0
        if previous and self.restore_enabled() and win32.is_window(previous) and self.foreground_ok() and not self.user_typing():
            win32.bring_to_front(previous)

    def foreground_ok(self) -> bool:
        return bool(self._pid) and win32.foreground_is(self._pid)

    # ------------------------------------------------------------------ reading
    def view(self):
        """A fresh View of the window, or an error string (``qq_window_missing`` / ``qq_content_unavailable``)."""
        found = self.find_window()
        if not found:
            return "qq_window_missing"
        try:
            root = uia.element_from_handle(found[0], uia.DUMP_PROPS)
            elements: list = []
            tree = uia.dump_tree(root, elements)
        except Exception:
            return "qq_content_unavailable"
        if not tree.get("children"):
            return "qq_content_unavailable"
        return View(T.annotate(tree), elements, self.config)

    def read_tree(self):
        """Annotated tree dict of the window, or an error string."""
        view = self.view()
        return view if isinstance(view, str) else view.tree

    def snapshot(self) -> dict:
        view = self.view()
        if isinstance(view, str):
            return {"error": view}
        tree = view.tree
        groups, allconv = self.groups, self.all_conversations
        return {
            "tree": tree,
            "activeConversation": T.current_group(tree, groups, allconv),
            "paused": self.shell.paused,
            "pid": self._pid,
            "conversationDetails": T.conversation_details(tree, groups, allconv),
            "idleSeconds": min(self.shell.typing_seconds(), 1e6),
        }

    def good_view(self):
        """A fresh view, or None when the window cannot be read."""
        view = self.view()
        return None if isinstance(view, str) else view

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
        view = self.view()
        if isinstance(view, str):
            return {"error": view}
        tree = view.tree
        rows = T.conversation_rows(tree, self.groups, self.all_conversations)
        keys = {T.conversation_key(title, self.groups): row for title, _, row in rows}
        if name not in keys:
            return {"error": "conversation_not_allowed"}
        if view.editor_node is not None and T.current_group(tree, self.groups, self.all_conversations) == name:
            return {"ok": True}
        if view.editor_node is not None and view.draft_present():
            return {"error": "draft_present"}
        if T.find_desc(tree, "会话列表") is None:
            tab = T.find(tree, lambda n: n.get("role") == "AXButton" and n.get("desc") == NAV_MESSAGES)
            element = view.element(tab)
            if element is not None:
                return {"ok": uia.invoke(element) or self.click_element(element)}
            return {"error": "open_qq_messages_tab"}
        row = view.element(keys[name])
        if row is None:
            return {"error": "group_not_in_visible_list"}
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
        view = self.good_view()
        if view is None or view.group() != group:
            return {"error": "image_context_changed"}
        mid = message_id
        if latest:
            excluded = set(exclude)
            candidates = []
            for item in T.nodes(view.message_list() or {}):
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
        row_node = view.row(mid)
        picture_node = view.picture(row_node)
        if row_node is None or picture_node is None:
            return {"error": "image_unavailable"}
        if self.user_typing():
            return {"error": "user_active_or_draft_present"}
        if view.editor() is None or view.draft_present():
            return {"error": "user_active_or_draft_present"}
        if not self.bring_into_view(view, view.element(row_node), view.element(picture_node)):
            return {"error": "image_not_visible"}
        rect = self.row_rect(view.element(picture_node))
        if not rect or rect[2] - rect[0] <= 10 or rect[3] - rect[1] <= 10:
            return {"error": "image_not_visible"}
        previous = clipboard.save()
        initial = clipboard.sequence_number()
        self.shell.pending_send = True
        try:
            if not self.activate():
                return {"error": "image_context_changed"}
            time.sleep(0.2)
            view = self.good_view()
            picture_node = view.picture(view.row(mid)) if view is not None else None
            if self.shell.paused or not self.foreground_ok() or view is None or view.group() != group or picture_node is None:
                return {"error": "image_context_changed"}
            rect = self.row_rect(view.element(picture_node))
            if not rect:
                return {"error": "image_not_visible"}
            win32.click((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2, right=True)
            item = None
            for _ in range(12):                    # the menu reaches the accessibility tree a moment after it appears
                time.sleep(0.15)
                item = self.find_copy_item()
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
            self.finish_focus()

    def bring_into_view(self, view: View, row, picture) -> bool:
        """Make the centre of ``picture`` visible inside the message list (UIA reports a half-hidden element as
        on screen, and a click on the hidden half would hit the input box or toolbar)."""
        listing = view.element(view.message_list())
        area = self.row_rect(listing if listing is not None else picture)
        for attempt in range(8):
            rect = self.row_rect(picture)
            if not (rect and area):
                return False
            cx, cy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
            if area[0] < cx < area[2] and area[1] + 8 < cy < area[3] - 8 and not uia.is_offscreen(picture):
                return True
            if attempt == 0:
                uia.scroll_into_view(row)
                time.sleep(0.25)
                continue
            below = cy >= area[3] - 8
            win32.scroll_wheel((area[0] + area[2]) // 2, (area[1] + area[3]) // 2, -3 if below else 3)
            time.sleep(0.3)
        return False

    def find_copy_item(self):
        """The context-menu entry 复制: a live search first (menu items are controls), then the raw tree of the
        QQ window, then any other QQ window (a menu may be a window of its own)."""
        label = "复制"
        root = None
        found = self.find_window()
        if found:
            try:
                root = uia.automation().ElementFromHandle(found[0])
            except Exception:
                root = None
        if root is not None:
            item = uia.find_first(root, name=label, ctype=50011)
            if item is not None:
                return item
        view = self.good_view()
        if view is not None:
            list_node = view.message_list()
            inside = {id(n) for n in T.nodes(list_node)} if list_node else set()
            for node in T.nodes(view.tree):
                if id(node) in inside:
                    continue
                if node.get("role") == "AXMenuItem" and node.get("desc") == label:
                    return view.element(node)
                if node.get("role") == "AXStaticText" and node.get("value") == label:
                    return view.element(node)
        for window in uia.top_level_windows(self.process):
            if window["visible"] and window["hwnd"] != self._hwnd:
                try:
                    top = uia.automation().ElementFromHandle(window["hwnd"])
                except Exception:
                    continue
                item = uia.find_first(top, name=label)
                if item is not None:
                    return item
        return uia.find_first(root, name=label) if root is not None else None

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

    def press_send(self, view: View) -> bool:
        button = view.send_button()
        return button is not None and uia.invoke(button)

    def clear_editor(self):
        """Select everything in the (focused) message box and delete it."""
        win32.press_key(win32.VK_A, win32.VK_CONTROL)
        time.sleep(0.05)
        win32.press_key(win32.VK_BACK)

    def send(self, group: str, text: str) -> dict:
        shell = self.shell
        if shell.paused or shell.pending_send or not group or not text or "\n" in text:
            return {"error": "send_not_allowed"}
        view = self.view()
        if isinstance(view, str):
            return {"error": "qq_window_missing"}
        if view.editor() is None:
            return {"error": "editor_unavailable"}
        actual = view.group()
        if actual != group:
            return {"error": "wrong_conversation", "actual_group": actual}
        if view.draft_present():
            return {"error": "draft_present"}
        if self.user_typing():
            return {"error": "user_typing"}
        shell.pending_send = True
        stage = "prepare"                      # prepare -> typed (text is in the box) -> submitted (may be on its way)
        try:
            if not self.activate():
                return {"error": "activation_or_draft_changed"}
            time.sleep(0.35)
            view = self.good_view()
            if (shell.paused or view is None or view.editor() is None or not self.foreground_ok() or view.group() != group
                    or view.draft_present()):
                return {"error": "activation_or_draft_changed"}
            editor = view.editor()
            if not self.focus_editor(editor):
                return {"error": "focus_changed"}
            time.sleep(0.15)
            if shell.paused or not self.foreground_ok() or not uia.has_focus(editor):
                return {"error": "focus_changed"}
            stage = "typed"
            win32.type_text(text)
            time.sleep(0.25)
            view = self.good_view()
            if (shell.paused or view is None or view.editor() is None or not self.foreground_ok() or view.group() != group
                    or view.draft().strip() != text.strip()):
                self.discard_own_draft(group, text)
                return {"error": "focus_or_draft_changed"}
            self.focus_editor(view.editor())
            stage = "submitted"                # from here on the message may be on its way: never clear, never resend
            if not self.press_send(view):
                win32.press_key(win32.VK_RETURN)
            time.sleep(0.6)
            view = self.good_view()
            if view is None or view.editor() is None or view.group() != group:
                return {"submitted": True, "awaiting_readback": True}
            if not view.draft_present():
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
            self.finish_focus()

    def discard_own_draft(self, group: str, text: str, clear_all: bool = False):
        """Remove what a failed send put into the message box. Text is only removed while it still is a prefix of
        what we typed; ``clear_all`` is for a box that was verified empty before we started (a pasted picture)."""
        try:
            view = self.good_view()
            if view is None or view.editor() is None or view.group() != group:
                return
            current = squash(view.draft())
            ours = view.draft_present() if clear_all else bool(current) and squash(text).startswith(current)
            if ours and self.foreground_ok():
                self.focus_editor(view.editor())
                self.clear_editor()
                self.log("cleared what a failed send left in the message box")
        except Exception as exc:  # best effort
            self.log(f"could not clear the message box: {exc}")

    def clear_draft(self, group: str, expected: str) -> dict:
        if self.user_typing():
            return {"error": "user_typing"}
        if self.shell.pending_send or not expected:
            return {"error": "editor_unavailable"}
        view = self.good_view()
        if view is None or view.editor() is None:
            return {"error": "editor_unavailable"}
        if view.group() != group:
            return {"error": "wrong_conversation"}
        if squash(view.draft()) != squash(expected):
            return {"error": "draft_differs"}
        if not self.activate():
            return {"error": "clear_failed"}
        time.sleep(0.3)
        view = self.good_view()
        if view is None or view.editor() is None or not self.focus_editor(view.editor()):
            return {"error": "clear_failed"}
        if squash(view.draft()) != squash(expected):
            return {"error": "draft_differs"}
        self.clear_editor()
        time.sleep(0.3)
        view = self.good_view()
        if view is None or view.editor() is None or view.draft_present():
            return {"error": "clear_failed"}
        self.log("cleared the bot's stuck draft after an uncertain send")
        self.finish_focus()
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
        view = self.good_view()
        if view is None or view.editor() is None or view.group() != group:
            return {"error": "wrong_conversation"}
        if view.draft_present():
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
            self.finish_focus()
            return result

        def ready(check_empty=False):
            """A fresh view when QQ is still in front, showing the right chat (and optionally an empty box)."""
            current = self.good_view()
            if (shell.paused or current is None or current.editor() is None or not self.foreground_ok()
                    or current.group() != group or (check_empty and current.draft_present())):
                return None
            return current

        try:
            if not self.activate():
                return finish({"error": "activation_or_draft_changed"})
            time.sleep(0.35)
            view = ready(check_empty=True)
            if view is None:
                return finish({"error": "activation_or_draft_changed"})
            self.focus_editor(view.editor())
            time.sleep(0.2)
            if shell.paused or not self.foreground_ok() or ready() is None:
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
            deadline = time.time() + 8.0       # QQ needs a moment to take the picture; poll instead of a fixed wait
            view = None
            while time.time() < deadline:
                time.sleep(0.4)
                view = ready()
                if view is None:
                    return finish({"error": "image_paste_context_changed"})
                if view.has_image():
                    break
            time.sleep(0.8)                    # let QQ finish processing before Send (it ignores Send while busy)
            self.focus_editor(view.editor())
            time.sleep(0.25)
            view = ready()
            if view is None:
                return finish({"error": "image_send_context_changed"})
            if not view.has_image():
                self.log("send_image: no picture appeared in the message box after pasting")
                self.discard_own_draft(group, typed, clear_all=True)
                return finish({"error": "image_paste_not_ready"})
            newlines_before = view.draft().count("\n")
            stage = "submitted"
            sent = self.press_send(view)
            if not sent:
                win32.press_key(win32.VK_RETURN)
            for attempt in (1, 2, 3):
                time.sleep(3.0)
                view = ready()
                if view is None:
                    return finish({"error": "image_send_context_changed"})
                if not view.draft_present():
                    method = ("click" if sent else "return") if attempt == 1 else "return+retry"
                    self.log(f"send_image done: attempt {attempt}, {method}")
                    return finish({"ok": True, "submitted": True, "method": method})
                added = view.draft().count("\n") - newlines_before
                self.log(f"send_image attempt {attempt} did not send")
                if added > 0:
                    for _ in range(min(added, 10)):
                        win32.press_key(win32.VK_BACK)
                if attempt == 3:
                    return finish({"error": "image_newline_instead_of_send" if added > 0 else "image_still_in_editor"})
                time.sleep(4.0)
                view = ready()
                if view is None:
                    return finish({"error": "image_send_context_changed"})
                self.focus_editor(view.editor())
                time.sleep(0.25)
                view = ready()
                if view is None:
                    return finish({"error": "image_send_context_changed"})
                if not self.press_send(view):
                    win32.press_key(win32.VK_RETURN)
            return finish({"error": "image_still_in_editor"})
        except Exception as exc:
            self.log(f"send_image failed at stage {stage}: {type(exc).__name__}: {exc}")
            return finish({"error": {"submitted": "image_send_context_changed", "pasted": "image_still_in_editor"}
                           .get(stage, "image_send_not_allowed")})
