"""Tests for the dumped-tree helpers and the backend's snapshot parser on a QQ-shaped tree (no QQ needed).

    .venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snapshot import parse_snapshot  # noqa: E402
from winapp import tree as T  # noqa: E402


def node(role="AXGroup", desc=None, value=None, dom=None, classes=(), children=()):
    result = {"role": role}
    if desc is not None:
        result["desc"] = desc
    if value is not None:
        result["value"] = value
    if dom is not None:
        result["domId"] = dom
    if classes:
        result["classes"] = list(classes)
    if children:
        result["children"] = list(children)
    return result


def text(value):
    return node("AXStaticText", value=value)


def conversation(title, preview="hi", count=None):
    info = [text(title)]
    if count:
        info.append(text(f"({count})"))
    info.append(node(classes=["summary-main"], children=[text(preview)]))
    return node(classes=["recent-contact-item"], children=[node(classes=["item__content"], children=[node(classes=["item__info"], children=info)])])


def message(mid, sender, body=None, image=None, mine=False, extra_classes=()):
    avatar = node(desc=sender, classes=["avatar-span"], children=[node(classes=["avatar-native"])])
    name = node(classes=["user-name"], children=[text(sender)])
    content = []
    if body is not None:
        content.append(text(body))
    if image:
        content.append(node("AXImage", desc=image, classes=["pic-element"]))
    wrapper = node(classes=["message-content__wrapper"], children=[node(classes=["msg-content-container", "container--self" if mine else "container--others"] + list(extra_classes),
                                                                          children=[node(classes=["message-content"], children=content)])])
    container = node(classes=["message-container"] + (["message-container--self"] if mine else []),
                     children=[avatar, name, wrapper, node(dom=f"md-tips__{mid}")])
    return node(dom=mid, classes=["ml-item"], children=[node(classes=["message"], children=[node(classes=["message__timestamp"], children=[text("12:00")]), container])])


def window(title, rows, messages, draft="", me="小我", group_member_list=True):
    editor = node("AXTextArea", value=draft, classes=["ProseMirror", "ExEditor-qq-msg-editor"])
    header = node("AXButton", desc=title, classes=["chat-header__contact-name"], children=[text(title)])
    aio = node(classes=["aio"], children=[
        node(classes=["chat-header"], children=[header]),
        node(classes=["group-chat"], children=[node(desc="消息列表", children=messages),
                                               node(classes=["chat-input-area"], children=[node(classes=["qq-msg-editor__root"], children=[editor])])]),
        node(desc="群成员列表") if group_member_list else node(desc="发起群聊"),
    ])
    sidebar = node(desc="会话列表", children=rows)
    top = node("AXButton", desc=f"{me}的头像", classes=["avatar", "user-avatar"])
    return T.annotate(node("AXWindow", children=[top, sidebar, aio]))


CONFIG = {"groups": ["测试群"], "self_names": ["小我"], "reply_all_conversations": False}


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.rows = [conversation("测试群", count=30), conversation("朋友"), conversation("重名"), conversation("重名")]
        self.messages = [message("7693942863185503147", "小明", "你好"), message("7768160473899629694", "小我", "收到", mine=True),
                         message("7693942907830551754", "小红", None, image="图片")]
        self.tree = window("测试群", self.rows, self.messages)

    def test_current_group_and_title(self):
        self.assertEqual(T.current_title(self.tree), "测试群")
        self.assertEqual(T.current_group(self.tree, ["测试群"], False), "测试群")

    def test_duplicate_titles_are_ambiguous_and_skipped(self):
        titles = [t for t, _, _ in T.conversation_rows(self.tree, ["测试群"], True)]
        self.assertEqual(titles, ["测试群", "朋友"])

    def test_only_configured_groups_unless_reply_all(self):
        self.assertEqual([t for t, _, _ in T.conversation_rows(self.tree, ["测试群"], False)], ["测试群"])

    def test_other_chat_gets_prefixed_key_when_reply_all(self):
        tree = window("朋友", self.rows, self.messages, group_member_list=False)
        self.assertEqual(T.current_group(tree, ["测试群"], True), "chat:朋友")
        self.assertEqual(T.current_group(tree, ["测试群"], False), "")
        details = T.conversation_details(tree, ["测试群"], True)
        self.assertEqual(details["chat:朋友"]["kind"], "private")
        self.assertEqual(details["测试群"]["kind"], "group")

    def test_editor_title_is_copied_from_header(self):
        self.assertEqual(T.editor_node(self.tree)["desc"], "测试群")

    def test_row_index_points_into_the_listing(self):
        rows = T.conversation_rows(self.tree, ["测试群"], True)
        listing = T.find_desc(self.tree, "会话列表")
        for title, index, row in rows:
            self.assertIs(listing["children"][index], row)


class ParseSnapshotTests(unittest.TestCase):
    def snapshot(self, tree):
        return {"tree": tree, "activeConversation": T.current_group(tree, CONFIG["groups"], False),
                "conversationDetails": T.conversation_details(tree, CONFIG["groups"], True)}

    def test_messages_senders_images_and_self_flag(self):
        rows = [conversation("测试群", count=30)]
        messages = [message("7693942863185503147", "小明", "你好"), message("7768160473899629694", "小我", "收到", mine=True),
                    message("7693942907830551754", "小红", None, image="图片"), message("7693942907830551755", "小红", None, image="动画表情")]
        parsed = parse_snapshot(self.snapshot(window("测试群", rows, messages)), CONFIG)
        self.assertEqual(parsed["group"], "测试群")
        self.assertTrue(parsed["messages_ready"])
        by_id = {m["id"]: m for m in parsed["messages"]}
        self.assertEqual(by_id["7693942863185503147"]["text"], "你好")
        self.assertEqual(by_id["7693942863185503147"]["sender"], "小明")
        self.assertFalse(by_id["7693942863185503147"]["self"])
        self.assertTrue(by_id["7768160473899629694"]["self"])
        self.assertTrue(by_id["7693942907830551754"]["has_image"])
        self.assertEqual(by_id["7693942907830551755"]["image_kind"], "sticker")

    def test_wrong_account_is_reported(self):
        rows = [conversation("测试群")]
        parsed = parse_snapshot(self.snapshot(window("测试群", rows, [], me="别人")), CONFIG)
        self.assertEqual(parsed["error"], "account_mismatch")

    def test_draft_text_is_exposed(self):
        rows = [conversation("测试群")]
        parsed = parse_snapshot(self.snapshot(window("测试群", rows, [], draft="写到一半")), CONFIG)
        self.assertEqual(parsed["draft"], "写到一半")

    def test_unconfigured_chat_has_no_messages(self):
        rows = [conversation("测试群"), conversation("朋友")]
        tree = window("朋友", rows, [message("7693942863185503147", "朋友", "hi")])
        parsed = parse_snapshot(self.snapshot(tree), CONFIG)
        self.assertEqual(parsed["messages"], [])


if __name__ == "__main__":
    unittest.main()
