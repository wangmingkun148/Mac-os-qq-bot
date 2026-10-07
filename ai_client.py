"""A client for any OpenAI-compatible chat-completions API (the one AI provider the user configures).

Pure request builders and response parsers plus the HTTP call; ``llm.Model`` decides what to ask.
"""
from __future__ import annotations
import base64
import json
from pathlib import Path
import queue
import re
import threading
import time
import urllib.error
import urllib.request

REPLY_SCHEMA = {"type": "object", "properties": {
    "should_reply": {"type": "boolean"}, "reply": {"type": "string"}, "reason": {"type": "string"},
}, "required": ["should_reply", "reply", "reason"], "additionalProperties": False}
EFFORTS = ("minimal", "low", "medium", "high")
# request fields some providers reject; they are dropped (and remembered) when the API complains about one
OPTIONAL_FIELDS = ("response_format", "temperature", "reasoning_effort")


def configured(ai):
    """True when the provider has everything a request needs."""
    return isinstance(ai, dict) and all(str(ai.get(field) or "").strip() for field in ("base_url", "api_key", "model"))


def chat_url(base_url):
    """``https://host/v1`` -> ``https://host/v1/chat/completions`` (a full endpoint address is kept as it is)."""
    url = str(base_url).strip().rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def encode_images(images):
    """[(id, path)] -> [(mime, base64)]."""
    pictures = []
    for _, path in images:
        suffix = Path(path).suffix.lower().lstrip(".") or "jpeg"
        pictures.append(("image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}",
                         base64.b64encode(Path(path).read_bytes()).decode("ascii")))
    return pictures


def prompt_path(base, name):
    return Path(base) / "prompts" / name


def response_schema(base, task):
    """JSON schema the answer must follow: the chat reply schema, or the task's ``<task>-schema.json`` if there is one."""
    if task == "reply":
        return REPLY_SCHEMA
    path = prompt_path(base, f"{task}-schema.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def schema_instruction(schema):
    """The output format spelled out in the system prompt (OpenAI-compatible endpoints only guarantee "some JSON
    object", so the model otherwise invents its own keys)."""
    return ("\n\n【输出格式】只输出一个 JSON 对象，字段名和类型必须与下面的 JSON Schema 完全一致："
            "不要添加其他字段（如 thought），不要把必填字段省略或写成 null，不要输出 JSON 之外的文字。\n"
            + json.dumps(schema, ensure_ascii=False))


def conform_strings(parsed, schema):
    """A missing or null string field of the schema becomes "" (a harmless gap such as an empty ``reason`` or
    ``source_url``); anything else is left for the caller to reject."""
    if not isinstance(parsed, dict) or not isinstance(schema, dict):
        return parsed
    for key, spec in (schema.get("properties") or {}).items():
        if isinstance(spec, dict) and spec.get("type") == "string" and parsed.get(key) is None:
            parsed[key] = ""
    return parsed


def request_body(model, instructions, payload, pictures, effort=None, temperature=0.7, skip=()):
    """Chat-completions body: the instructions as the system message, the payload (and any pictures) as the user's."""
    text = json.dumps(payload, ensure_ascii=False)
    content = text if not pictures else [{"type": "text", "text": text}] + [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}} for mime, data in pictures]
    body = {"model": model, "messages": [{"role": "system", "content": instructions}, {"role": "user", "content": content}],
            "response_format": {"type": "json_object"}, "temperature": temperature}
    if effort in EFFORTS:
        body["reasoning_effort"] = effort
    return {key: value for key, value in body.items() if key not in skip}


def rejected_field(body, error):
    """The optional field a 400/422 error complains about (it is in ``body`` and named in the message), or None."""
    message = str(error)
    if "HTTP 400" not in message and "HTTP 422" not in message:
        return None
    return next((field for field in OPTIONAL_FIELDS if field in body and field in message), None)


# -- transport ------------------------------------------------------------------------------------

class AITimeout(RuntimeError):
    """No response within the overall deadline; the request can safely be sent again."""


def describe_timing(trace, now=None):
    """One readable line saying where the time went: request size, waiting for the response."""
    now = time.monotonic() if now is None else now
    parts = []
    if "bytes" in trace:
        images = trace.get("images", 0)
        parts.append(f"请求体 {trace['bytes'] / 1e6:.1f}MB" + (f"（含 {images} 张图）" if images else ""))
    if "sent_at" in trace:
        parts.append(f"发出后等了 {now - trace['sent_at']:.1f}s" + ("" if "response_seconds" in trace else " 仍无响应"))
    return "；".join(parts) or "还没发出请求"


def post_json(url, body, api_key, total_timeout, trace=None):
    """POST ``body`` in a worker thread so the caller can enforce one overall deadline. ``trace`` (a dict) receives
    timings so a failure can say which phase stalled."""
    outcome = queue.Queue(maxsize=1)
    trace = {} if trace is None else trace

    def fetch():
        try:
            data = json.dumps(body).encode()
            request = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST")
            trace["bytes"] = len(data)
            trace["sent_at"] = time.monotonic()
            with urllib.request.urlopen(request, timeout=total_timeout) as response:
                value = json.loads(response.read())
            trace["response_seconds"] = time.monotonic() - trace["sent_at"]
            outcome.put((True, value))
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode(errors="replace")
            except Exception:
                detail = ""
            try:
                detail = json.dumps(json.loads(detail), ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass
            if api_key:
                detail = detail.replace(api_key, "***")
            outcome.put((False, RuntimeError(f"AI 接口请求失败：HTTP {exc.code} {detail[:300]}".strip())))
        except urllib.error.URLError as exc:
            outcome.put((False, RuntimeError(f"AI 接口网络连接失败：{str(getattr(exc, 'reason', exc))[:120]}（{describe_timing(trace)}）")))
        except Exception as exc:
            outcome.put((False, exc))

    threading.Thread(target=fetch, daemon=True, name="ai-http").start()
    try:
        success, result = outcome.get(timeout=total_timeout)
    except queue.Empty as exc:
        raise AITimeout(f"AI 接口请求超过 {total_timeout:g} 秒，已放弃本次回复（{describe_timing(trace)}）") from exc
    if not success:
        raise result
    if not isinstance(result, dict):
        raise RuntimeError("AI 接口没有返回有效响应")
    return result


# -- responses ------------------------------------------------------------------------------------

def extract_json(text):
    """The JSON object in a model's answer: plain JSON, JSON in a code fence, or the first {...} in surrounding text
    (some models think aloud in <think> blocks or ignore JSON mode)."""
    text = re.sub(r"<think>.*?</think>", "", str(text), flags=re.S | re.I).strip()
    candidates = [text, re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start:end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object")


def parse_response(result):
    """Return (answer dict, usage dict) from a raw chat-completions response."""
    try:
        message = result["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, list):           # some providers answer with a list of parts
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        parsed = extract_json(content)
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise RuntimeError("AI 接口没有返回有效 JSON（请确认模型支持 JSON 输出）") from exc
    usage = result.get("usage") or {}
    extra = {"input_tokens": usage.get("prompt_tokens", 0) or 0, "output_tokens": usage.get("completion_tokens", 0) or 0}
    reasoning = message.get("reasoning_content") or message.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        extra["thoughts"] = [reasoning.strip()]
    return parsed, extra
