"""Turn the native accessibility snapshot of the QQ window into conversations and messages."""
from __future__ import annotations


def nodes(node):
    yield node
    for child in node.get("children", []):
        yield from nodes(child)


def message_images(node):
    if "reply-element" in node.get("classes", []):
        return
    if node.get("role") == "AXImage":
        yield node
    for child in node.get("children", []):
        yield from message_images(child)


def find(node, **attrs):
    return next((n for n in nodes(node) if all(n.get(k) == v for k, v in attrs.items())), None)


def texts(node):
    return [n.get("value", "") for n in nodes(node) if n.get("role") == "AXStaticText" and n.get("value")]


def same_text(actual, expected):
    """QQ 可能会改写空白，或把 @ 提醒渲染成额外节点；比对时忽略空白差异。"""
    a = "".join(str(actual).split())
    b = "".join(str(expected).split())
    if not a or not b:
        return False
    if a == b:
        return True
    # 兜底：QQ 在正文中额外插入时间戳之类的内容时，正文本身仍应完整出现。
    return len(b) >= 8 and b in a


def parse_snapshot(snapshot, config):
    if "error" in snapshot:
        return {"error": snapshot["error"]}
    root = snapshot.get("tree", {})
    self_names = config["self_names"]
    if not any(find(root, role="AXButton", desc=name + "的头像") for name in self_names):
        return {"error": "account_mismatch"}
    conversations = {}
    details = snapshot.get("conversationDetails", {})
    listing = find(root, desc="会话列表")
    if listing:
        rows = []
        for child in listing.get("children", []):
            values = texts(child)
            info = next((n for n in nodes(child) if "item__info" in n.get("classes", [])), child)
            title = next((n.get("value", "") for n in nodes(info) if n.get("role") == "AXStaticText" and n.get("value")), "")
            if title:
                rows.append((title, values))
        for title, values in rows:
            if sum(t == title for t, _ in rows) != 1:
                continue
            if title in config["groups"]:
                key = title
            elif config.get("reply_all_conversations"):
                key = "chat:" + title
            else:
                continue
            conversations[key] = "\n".join(values)
            details.setdefault(key, {"title": title, "kind": "group" if title in config["groups"] else "unknown"})
    editor = next((n for n in nodes(root) if n.get("role") == "AXTextArea"), {})
    title = editor.get("desc", "")
    if not title:
        header = next((n for n in nodes(root) if n.get("role") == "AXButton" and n.get("desc") in config["groups"]), {})
        title = header.get("desc", "")
    group = title if title in config["groups"] else "chat:" + title if title else ""
    if "activeConversation" in snapshot:
        group = snapshot["activeConversation"]
    result = {"group": group, "conversations": conversations, "conversation_details": details, "messages": [], "messages_ready": False, "draft": editor.get("value", "")}
    if group not in conversations and group not in config["groups"]:
        return result
    if group not in config["groups"] and not config.get("reply_all_conversations"):
        return result
    listing = find(root, desc="消息列表")
    if not listing:
        return result
    result["messages_ready"] = True
    for row in nodes(listing):
        mid = row.get("domId", "")
        if not mid.isdecimal() or len(mid) < 10:
            continue
        avatar = next((n for n in nodes(row) if n.get("role") == "AXGroup" and n.get("desc")), None)
        if not avatar:
            continue  # System notices do not have a sender avatar.
        sender = avatar["desc"]
        parent = next((n for n in nodes(row) if any(c is avatar for c in n.get("children", []))), None)
        if not parent:
            continue
        content = []
        has_image = False
        image_kind = ""
        after_avatar = False
        for child in parent.get("children", []):
            if child is avatar:
                after_avatar = True
                continue
            if not after_avatar or child.get("domId", "").startswith(("msg-extra-", "md-status", "md-tips")):
                continue
            values = texts(child)
            if values and values[0] == sender:  # Display name and group level header.
                continue
            content.extend(values)
            pictures = list(message_images(child))
            has_image = has_image or bool(pictures)
            if any("动画" in str(n.get("desc", "")) or "表情" in str(n.get("desc", "")) for n in pictures):
                image_kind = "sticker"
        text = " ".join(content).strip()
        classes = {c for n in nodes(row) for c in n.get("classes", [])}
        own = "message-container--self" in classes or "container--self" in classes
        if not classes:
            own = sender in self_names
        result["messages"].append({"id": mid, "sender": sender, "text": text[:1800], "has_image": has_image, "image_kind": image_kind, "content_pending": not text and not has_image, "self": own, "bot": "qq-bot-label" in classes})
    mark_sticker(result["messages"], conversations.get(group, ""))
    return result


STICKER_PREVIEWS = ("[动画表情]", "[表情]")


def mark_sticker(messages, preview):
    """The chat itself shows a sticker and a photo the same way; the conversation list preview does not ("[动画表情]"
    vs "[图片]"). When the preview names a sticker as the latest message, mark that message (if the preview's sender
    prefix, "名字：", matches) as image_kind="sticker". Only the latest message can be told apart this way."""
    lines = [line.strip() for line in str(preview or "").splitlines() if line.strip()]
    if not lines or lines[-1] not in STICKER_PREVIEWS or not messages:
        return
    last = messages[-1]
    prefix = lines[-2][:-1] if len(lines) >= 2 and lines[-2].endswith(("：", ":")) else None
    if last.get("has_image") and not last.get("text") and not last.get("self") and prefix in (None, last.get("sender")):
        last["image_kind"] = "sticker"
