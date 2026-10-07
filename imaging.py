"""Image generation request quota and the image generation client."""
from __future__ import annotations
import base64
import json
import os
import struct
import threading
import time
import uuid
import urllib.error
import urllib.request
import fsutil


class ImageQuota:
    def __init__(self, path, max_per_24h=2, unlimited=()):
        self.path = path
        self.max_per_24h = max_per_24h
        self.unlimited = set(unlimited)
        self.lock = threading.Lock()

    def _load(self):
        try:
            data = json.loads(self.path.read_text())
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def remaining(self, sender, now=None):
        if sender in self.unlimited:
            return None
        now = time.time() if now is None else now
        cutoff = now - 86400
        with self.lock:
            recent = [value for value in self._load().get(sender, []) if isinstance(value, (int, float)) and value > cutoff]
        return max(self.max_per_24h - len(recent), 0)

    def record(self, sender, now=None):
        if sender in self.unlimited:
            return
        now = time.time() if now is None else now
        cutoff = now - 86400
        with self.lock:
            data = self._load()
            data[sender] = [value for value in data.get(sender, []) if isinstance(value, (int, float)) and value > cutoff] + [now]
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            os.chmod(tmp, 0o600)
            fsutil.replace(tmp, self.path)


class ImageGenerator:
    """Calls the image model the owner configured. Two request styles are understood, chosen by the address:
    an OpenAI-style ``.../images/generations`` endpoint, or the DashScope-style ``.../multimodal-generation/...`` one."""

    def __init__(self, base, config):
        self.base = base
        self.config = config.get("image_generation", {})

    def _call(self, prompt):
        c = self.config
        size = c.get("size", "1024*1024")
        openai_style = "/images/" in c["endpoint"]
        if openai_style:
            body = {"model": c["model"], "prompt": prompt, "n": 1, "size": str(size).replace("*", "x")}
        else:
            body = {"model": c["model"], "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
                    "parameters": {"prompt_extend": True, "watermark": False, "n": 1, "size": str(size).replace("x", "*")}}
        request = urllib.request.Request(
            c["endpoint"], data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": f"Bearer {c['api_key']}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=c.get("timeout_seconds", 240)) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300].replace(c.get("api_key", "\0"), "***")
            raise RuntimeError(f"图片生成接口失败：HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("图片生成接口连接失败") from exc
        try:
            if openai_style:
                item = result["data"][0]
                return base64.b64decode(item["b64_json"]) if item.get("b64_json") else self._download(item["url"]), openai_style
            return self._download(result["output"]["choices"][0]["message"]["content"][0]["image"]), openai_style
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            message = str(result.get("message") or (result.get("error") or {}).get("message") or "接口未返回图片")[:240] if isinstance(result, dict) else "接口未返回图片"
            raise RuntimeError(message) from exc

    @staticmethod
    def _download(url):
        if not isinstance(url, str) or not url.startswith("https://"):
            raise RuntimeError("图片生成接口返回了无效地址")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    return response.read(26_000_001)
            except urllib.error.HTTPError as exc:
                if attempt == 2 or exc.code not in (408, 429, 500, 502, 503, 504):
                    raise RuntimeError(f"生成图片下载失败：HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 2:
                    reason = getattr(exc, "reason", exc)
                    raise RuntimeError(f"生成图片下载失败：{str(reason)[:160]}") from exc
            time.sleep(attempt + 1)

    def generate(self, prompt):
        c = self.config
        image, openai_style = self._call(prompt)
        kind = ("png" if image.startswith(b"\x89PNG\r\n\x1a\n") else "jpg" if image.startswith(b"\xff\xd8\xff") else
                "webp" if image[:4] == b"RIFF" and image[8:12] == b"WEBP" else None)
        if kind is None or len(image) > 25_000_000 or len(image) < 24:
            raise RuntimeError("生成结果不是有效的图片（PNG / JPEG / WebP）")
        width = height = None
        if kind == "png":
            width, height = struct.unpack(">II", image[16:24])
            expected = str(c.get("size", "1024*1024")).replace("x", "*")
            if not openai_style and f"{width}*{height}" != expected:      # this style of API is told exactly what size to make
                raise RuntimeError(f"图片尺寸不是要求的 {expected}，实际为 {width}*{height}")
        path = self.base / "runtime" / f"generated-{uuid.uuid4()}.{kind}"
        path.write_bytes(image)
        os.chmod(path, 0o600)
        return {"path": str(path), "width": width, "height": height}
