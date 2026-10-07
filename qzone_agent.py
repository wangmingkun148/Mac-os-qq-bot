"""Choose one QQ Space interaction using the configured model backend."""
import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from image_prep import save_jpeg
from llm import Model
from style import load_style_profile
from temporal_relevance import today


def skipped(reason):
    return {"post_id": "", "like": False, "comment": "", "reason": reason}


def download_image(url, directory, index):
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "qpic.cn" or host.endswith(".qpic.cn")):
        raise ValueError("图片地址不可读取")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://user.qzone.qq.com/"})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read(15 * 1024 * 1024 + 1)
        content_type = response.headers.get_content_type()
    if not content_type.startswith("image/") or not data or len(data) > 15 * 1024 * 1024:
        raise ValueError("图片没有完整读取")
    if data.startswith((b"GIF87a", b"GIF89a")) or b"acTL" in data[:65536] or (data[:4] == b"RIFF" and b"ANIM" in data):
        raise ValueError("动画内容暂不读取")
    source, target = directory / f"{index}.source", directory / f"{index}.jpg"
    source.write_bytes(data)
    if not save_jpeg(source, target, 1600):
        raise ValueError("图片无法解码")
    return target


def prepare_posts(base, posts, directory):
    history = base / "runtime/qzone-actions.json"
    records = json.loads(history.read_text()) if history.exists() else []
    handled = {record.get("id") for record in records}
    usable, images = [], []
    reason = "暂无未处理的可读动态"
    for post in posts[:10]:
        if not post.get("id") or post["id"] in handled or post.get("own_comment") or post.get("advertisement"):
            continue
        kind = post.get("media_kind", "text")
        if kind not in ("text", "images"):
            reason = "视频或不可读取的内容不互动"
            continue
        urls = post.get("image_urls", [])
        count = post.get("image_count", 0)
        if kind == "images" and (not count or len(urls) != count):
            reason = "图片未完整读取，跳过整条动态"
            continue
        if kind == "text" and (count or urls):
            reason = "媒体类型未确认，跳过整条动态"
            continue
        if kind == "text" and not post.get("text"):
            continue
        attached = []
        try:
            for url in urls:
                image_id = f"{post['id']}:image:{len(attached) + 1}"
                path = download_image(url, directory, len(images) + len(attached))
                attached.append((image_id, path))
        except Exception:
            reason = "图片读取或解码失败，跳过整条动态"
            continue
        images.extend(attached)
        usable.append({key: value for key, value in post.items() if key != "image_urls"})
        usable[-1]["attached_image_ids"] = [image_id for image_id, _ in attached]
    return usable, images, reason


def choose(base, posts, recent):
    with tempfile.TemporaryDirectory(prefix="qzone-images-", dir=base / "runtime") as temporary:
        usable, images, reason = prepare_posts(base, posts, Path(temporary))
        if not usable:
            return skipped(reason)
        return generate(base, usable, recent, images)


def generate(base, usable, recent, images):
    config = json.loads((base / "config.json").read_text())
    group = config.get("groups", [""])[0]
    payload = {"current_date": today(), "posts": usable, "recent_comments": recent[-12:],
               "style_profile": load_style_profile(base, group, config.get("style_profile_max_chars", 1999)),
               "attached_image_order": [image_id for image_id, _ in images]}
    model = Model(base, config)
    result, usage, seconds, used = model.run_task("qzone", payload, images=images)
    name = used["model"]
    if not isinstance(result.get("post_id"), str) or type(result.get("like")) is not bool or not isinstance(result.get("comment"), str) or not isinstance(result.get("reason"), str):
        raise ValueError("空间互动结果格式无效")
    valid = {p["id"] for p in usable}
    if result["post_id"] and result["post_id"] not in valid:
        raise ValueError("模型选择了不在当前列表的动态")
    result["comment"] = " ".join(result["comment"].splitlines()).strip()
    if len(result["comment"]) > 80 or "http" in result["comment"].lower() or "@" in result["comment"]:
        raise ValueError("评论超长或包含不支持的链接、提及")
    if not result["post_id"] and (result["like"] or result["comment"]):
        raise ValueError("缺少评论目标")
    return {**result, "model": name, "seconds": seconds}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    base = Path(args.base)
    try:
        job = json.loads(Path(args.input).read_text())
        output = {"ok": True, "action": choose(base, job["posts"], job.get("recent", []))}
    except Exception as exc:
        output = {"ok": False, "error": str(exc)[:300]}
    target = Path(args.output)
    target.write_text(json.dumps(output, ensure_ascii=False))
    os.chmod(target, 0o600)
