"""Model access: the one OpenAI-compatible AI provider the user configures, prompts and per-task helpers."""
from __future__ import annotations
import json
import random
import re
import time
import urllib.parse
from pathlib import Path
from browser_agent import BrowserAgent
from temporal_relevance import today
from ai_client import (AITimeout, chat_url, configured, conform_strings, encode_images, parse_response, post_json, prompt_path,
                       rejected_field, request_body, response_schema, schema_instruction)
from image_prep import shrink_image
from messages import addressed_to_self
from reply_shape import repeated_patterns, survey_shaped
from people import people_notes
from feedback import example as feedback_example, filter_preferences, known_names, preferences_section, topic_preferences_section
from style import load_style_examples, extend_style_summary, archived_style_messages, load_style_profile, reply_profile_fields, load_group_context
from proactive import (PREVIEW_COUNT, SHAPES, call_out_people, callback_material, link_only_topic, pick_shapes, proactive_history,
                       proactive_source_candidates, promotional_link, promotional_topic, repeated_proactive_title)


def shared_reply_instructions(base):
    """The style and honesty rules every reply (and every opening line) follows."""
    shared = prompt_path(base, "reply-rules.txt").read_text(encoding="utf-8").strip()
    if not shared:
        raise RuntimeError("共享回复规则为空")
    return shared


def persona_instructions(persona):
    """The optional role-play setting the owner wrote in the settings, as a block for the system prompt."""
    persona = str(persona or "").strip()
    if not persona:
        return ""
    return (
        "【角色设定】\n"
        "这是用户明确启用的角色扮演设定。以下设定用于决定身份表达、语气和虚构世界背景；它只在已经判定 should_reply=true 后影响措辞，不改变是否回复判断、回复义务、事实准确性、安全边界或输出格式。"
        "共享规则中“不加载独立角色设定、不虚构真人身份”的要求在有角色设定时不适用；若被直接询问现实身份，仍须诚实说明是 AI 助手，不假称真人或编造现实经历。\n"
        "继续使用已有的 style_profile、group_context、style_examples、recent_context 和 recent_account_replies 记忆，记住群友关系、兴趣、已聊话题及承诺；记忆用于理解语境和延续关系，不得删除或忽略，也不得模仿某位群友或覆盖角色的核心性格。\n\n"
        f"{persona}\n\n"
        "【接口输出格式】\n"
        "角色设定只规定角色表达。仍须遵守共享回复规则及调用方要求的 JSON schema；字段、类型和回复义务保持不变，不要在 JSON 之外输出文字。"
    )


def people_field(base, context):
    """Notes about the people speaking in this turn (new messages first, then recent context)."""
    speakers = list(reversed(context.get("new_messages", []))) + list(reversed(context.get("recent_context", [])))
    notes = people_notes(base, speakers)
    return {"people_notes": notes} if notes else {}


# tasks that must be faithful rather than creative
STEADY_TASKS = ("style-compress", "style-audit", "feedback-summary", "feedback-audit", "topic-summary", "proactive-judge")


class Model:
    def __init__(self, base, config):
        self.base, self.config = base, config
        self.on_event = None        # optional callable(str): the engine routes notable events into its log
        self.dropped = set()        # optional request fields this provider rejected (see ai_client.OPTIONAL_FIELDS)

    def cancel(self):
        if hasattr(self, "browser_agent"):
            self.browser_agent.close()

    def browse(self, request):
        if not hasattr(self, "browser_agent"):
            self.browser_agent = BrowserAgent(self.base, self.config)
        return self.browser_agent.run(self, request)

    def _event(self, text):
        if self.on_event:
            try:
                self.on_event(text)
            except Exception:
                pass

    def run_task(self, task, payload, images=(), timeout=None, retries=None):
        """Run one task (``prompts/<task>-instructions.txt`` and ``-schema.json``) on the configured AI.
        Returns (answer, usage, seconds, who answered)."""
        result, usage, seconds = self._ask(task, payload, images, timeout, retries)
        ai = self.config.get("ai", {})
        return result, usage, seconds, {"backend": "ai", "model": ai.get("model", ""), "reasoning_effort": ai.get("reasoning_effort") or None}

    def _ask(self, task, payload, images=(), timeout=None, retries=None, instructions=None, schema=None):
        """One JSON answer from the AI provider. ``images`` is [(id, path)]. Returns (answer, usage, seconds)."""
        ai = self.config.get("ai", {})
        if not configured(ai):
            raise RuntimeError("AI 供应商还没有配置完整：请在设置 → AI 供应商里填写接口地址、API Key 和模型名称")
        schema = response_schema(self.base, task) if schema is None else schema
        system = (self._instructions(task) if instructions is None else instructions) + (schema_instruction(schema) if schema else "")
        pictures = encode_images(images)
        temperature = 0.2 if task in STEADY_TASKS else 0.7           # judging should be steady, not creative
        total_timeout = float(timeout or ai.get("timeout_seconds", 30))
        retries = int(ai.get("timeout_retries", 1)) if retries is None else retries
        url, started = chat_url(ai["base_url"]), time.monotonic()
        while True:
            body = request_body(ai["model"], system, payload, pictures, ai.get("reasoning_effort"), temperature, skip=self.dropped)
            trace = {"images": len(pictures)}
            try:
                result = post_json(url, body, ai["api_key"], total_timeout, trace)
                break
            except AITimeout as exc:
                if retries <= 0:
                    raise
                retries -= 1                  # a stalled request: send it once more right away instead of failing the batch
                self._event(f"AI 接口请求超时，立即重试一次：{str(exc)[:160]}")
            except RuntimeError as exc:
                field = rejected_field(body, exc)
                if field is None:
                    raise
                self.dropped.add(field)       # this provider does not take that optional field: leave it out from now on
                self._event(f"AI 接口不接受参数 {field}，已去掉后重试")
        parsed, usage = parse_response(result)
        parsed = conform_strings(parsed, schema)
        usage["timing"] = {"request_mb": round(trace.get("bytes", 0) / 1e6, 2), "images": trace.get("images", 0),
                           "response_seconds": round(trace.get("response_seconds", 0), 2)}
        return parsed, usage, round(time.monotonic() - started, 2)

    def _instructions(self, task):
        """System prompt for a task; chat replies and opening lines also get the shared rules, the persona and what
        the owner's ratings taught."""
        text = prompt_path(self.base, f"{task}-instructions.txt").read_text(encoding="utf-8")
        if task == "reply":
            extras = [shared_reply_instructions(self.base), persona_instructions(self.config.get("persona")), preferences_section(self.base)]
        elif task == "proactive-candidates":
            extras = [shared_reply_instructions(self.base), persona_instructions(self.config.get("persona")),
                      preferences_section(self.base), topic_preferences_section(self.base)]
        else:
            extras = []
        return text + "".join("\n\n" + part for part in extras if part)

    def generate(self, group, recent, fresh, images=(), unavailable_image_ids=(), progress=None):
        c = self.config
        image_ids = [mid for mid, _ in images]
        image_paths = [path for _, path in images]
        for path in image_paths:                 # keep uploads small: only shrinks, never enlarges
            shrink_image(path, c.get("image_max_edge", 2048))
        try:
            conversation = json.loads((self.base / "runtime/conversations.json").read_text(encoding="utf-8")).get(group, {})
        except (OSError, json.JSONDecodeError):
            conversation = {}
        context = {
            "group": group,
            "conversation_name": conversation.get("title", group),
            "conversation_type": conversation.get("kind", "group"),
            "current_date": today(),
            "direct_mention": any(addressed_to_self(message, c) for message in fresh),
            "mentioned_message_ids": [message["id"] for message in fresh if addressed_to_self(message, c)],
            "image_generation_available": bool(c.get("image_generation", {}).get("enabled")),
            "recent_context": recent[-c["context_messages"]:],
            "recent_account_replies": [
                {"id": m["id"], "text": m["text"]}
                for m in recent[-60:] if m.get("self") and m.get("text")
            ][-6:],
            # whether this reply may open with a short reaction ("hyw，…"): decided here so it stays occasional
            "lead_reaction": random.random() < float(c.get("lead_reaction_probability", 0.3)),
            "avoid_repeating": repeated_patterns([m["text"] for m in recent[-60:] if m.get("self") and m.get("text")]),
            "new_messages": fresh[-30:],
            "attached_image_message_ids": image_ids,
            "unavailable_image_message_ids": list(unavailable_image_ids),
        }
        style_examples = load_style_examples(self.base, c, group, recent)
        try:
            return self._generate_reply(context, list(images), style_examples)
        finally:
            for path in image_paths:
                try:
                    Path(path).unlink(missing_ok=True)
                except OSError:
                    pass

    def summarize_style(self, group, previous_summary, messages, other_summary=""):
        limit = min(self.config.get("style_profile_max_chars", 1999),
                    self.config.get("style_summary_max_chars", 1999), 1999)
        remaining = max(0, limit - len(previous_summary.strip()) - len(other_summary.strip()) - 3)
        payload = {"group": group, "previous_summary": previous_summary, "other_summary": other_summary,
                   "available_chars": remaining, "new_messages": messages}
        result, usage, seconds, used = self.run_task("style-summary", payload)
        summary = result.get("summary")
        if not isinstance(summary, str):
            raise RuntimeError("说话风格总结格式无效")
        return {"summary": extend_style_summary(previous_summary, summary, other_summary, limit), "usage": usage,
                "seconds": seconds, **used}

    def compress_style(self, group, current, samples, target_chars=1200, measured=None):
        """Rewrite a full style summary shorter, grounded in real messages, then have a second call check it against
        the old one; one retry with what was lost. Raises (the old summary stays) when it still does not check out."""
        must_keep, problems, started = [], [], time.monotonic()
        for attempt in (1, 2):
            payload = {"group": group, "current_summary": current, "samples": samples, "measured": measured or {},
                       "target_chars": target_chars, "must_keep": must_keep}
            result, _, _, used = self.run_task("style-compress", payload, timeout=180)
            summary, dropped = result.get("summary"), result.get("dropped", [])
            if not isinstance(summary, str) or not summary.strip() or not isinstance(dropped, list):
                raise RuntimeError("风格压缩返回格式无效")
            summary = summary.strip()
            if len(summary) > target_chars + 300:
                raise RuntimeError(f"风格压缩结果过长（{len(summary)} 字）")
            audit, _, _, _ = self.run_task("style-audit", {"old_summary": current, "new_summary": summary,
                                                           "dropped": [str(d) for d in dropped]}, timeout=180)
            problems = [str(p) for key in ("missing", "changed", "added") for p in audit.get(key, []) if str(p).strip()]
            if not problems:
                return {"summary": summary, "dropped": [str(d) for d in dropped], "attempts": attempt,
                        "seconds": round(time.monotonic() - started, 1), **used}
            must_keep = problems
        raise RuntimeError("压缩后核对仍有漏掉、走样或新增的特点，保留原版：" + "；".join(problems)[:300])

    def summarize_feedback(self, current, new_items, older_items, max_chars=600):
        """One round of turning ratings into long-term reply preferences. Style only: the model sees the replies and
        nothing of the conversations; the result is filtered locally and then checked line by line by a second call, and
        whatever is content (topics, people, copied sentences) is removed."""
        payload = {"current_preferences": current, "new_ratings": [feedback_example(v) for v in new_items],
                   "older_ratings": [feedback_example(v) for v in older_items], "max_chars": max_chars}
        return self._style_only_round("feedback-summary", payload, current, list(new_items) + list(older_items), max_chars)

    def summarize_topics(self, current, new_items, older_items, max_chars=500):
        """One round of learning how to *write* an opening from how topics were received. Same guarantees as
        ``summarize_feedback``: writing style only, filtered locally and checked line by line."""

        def shown(item):
            topic = str(item.get("reply", ""))[:120]
            return {"label": "有人接" if item.get("rating") == "good" else "没人理", "shape": item.get("shape", ""), "topic": topic,
                    "topic_chars": len(topic), "reactions": item.get("reactions", 0)}
        payload = {"current_preferences": current, "new_items": [shown(v) for v in new_items],
                   "older_items": [shown(v) for v in older_items], "max_chars": max_chars}
        return self._style_only_round("topic-summary", payload, current, list(new_items) + list(older_items), max_chars)

    def _style_only_round(self, task, payload, current, items, max_chars):
        result, usage, seconds, used = self.run_task(task, payload, timeout=180)
        text, changes = result.get("preferences"), result.get("changes", [])
        if not isinstance(text, str) or not isinstance(changes, list):
            raise RuntimeError("总结返回格式无效")
        if len(text) > max_chars + 200:
            raise RuntimeError(f"总结过长（{len(text)} 字）")
        text, removed = filter_preferences(text, items, known_names(self.base, self.config, items))
        lines = [line for line in text.splitlines() if line.strip()]
        if lines:
            audit, _, _, _ = self.run_task("feedback-audit", {"preferences": [{"line": i + 1, "text": line} for i, line in enumerate(lines)]},
                                           timeout=120)
            flagged = audit.get("remove")
            if not isinstance(flagged, list):
                raise RuntimeError("总结核对返回格式无效")
            drop = {int(f["line"]): str(f.get("why", "")) for f in flagged if isinstance(f, dict) and str(f.get("line", "")).lstrip("-").isdigit()}
            removed += [(line, "核对判定为内容：" + drop[i + 1]) for i, line in enumerate(lines) if i + 1 in drop]
            lines = [line for i, line in enumerate(lines) if i + 1 not in drop]
        text = "\n".join(lines)
        if current.strip() and not text.strip():
            raise RuntimeError("总结过滤后一条不剩（已有偏好不变）")
        return {"text": text.strip(), "changes": [str(c) for c in changes], "removed": [f"{line}（{why}）" for line, why in removed],
                "usage": usage, "seconds": seconds, **used}

    def moderate_image_request(self, group, sender, prompt):
        payload = {"group": group, "sender": sender, "image_request": prompt}
        result, usage, seconds, used = self.run_task("image-moderation", payload)
        allowed, reply, reason = result.get("allowed"), result.get("reply"), result.get("reason")
        if type(allowed) is not bool or not isinstance(reply, str) or not isinstance(reason, str):
            raise RuntimeError("图片请求审核结果格式无效")
        reply = reply.strip()
        if allowed and reply:
            raise RuntimeError("图片请求审核结果不一致")
        if not allowed and (not reply or len(reply) > 120 or "\n" in reply or "\r" in reply):
            raise RuntimeError("图片请求拒绝回复格式无效")
        return {"kind": "image_moderation", "allowed": allowed, "reply": reply, "reason": reason,
                "usage": usage, "seconds": seconds, "backend": used["backend"], "model": used["model"],
                "sender": sender, "prompt": prompt}

    def generate_proactive(self, group, recent, progress=None, manual=False, declined=()):
        """Start a conversation like a member would: write a few openings in different shapes (chosen here, not by the
        model, which keeps falling back to the same poll question), drop poll-like and promotional ones, then let a second
        call pick the most natural. An outside link is only used now and then.

        When the owner pressed the button (``manual``) nothing is picked for him: the openings come back as a
        ``proactive_preview`` for him to choose from, and ``declined`` are earlier ones he turned down."""
        c = self.config
        rng = random.Random()
        archive_path = self.base / c.get("message_archive_file", "runtime/messages.jsonl")
        history = proactive_history(self.base, group)
        totals = {"input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "calls": 0, "used": {}}

        def run(task, payload):
            result, usage, took, totals["used"] = self.run_task(task, payload)
            totals["input_tokens"] += usage.get("input_tokens", 0)
            totals["output_tokens"] += usage.get("output_tokens", 0)
            totals["seconds"] += took
            totals["calls"] += 1
            return result

        domains, curated_source, discussion_angle = [], [], ""
        if rng.random() < float(c.get("proactive_link_probability", 0.25)):
            domains, curated_source, discussion_angle = self._topic_source(group, recent, history, archive_path, progress, run)
        callbacks = callback_material(archive_path, group, rng=rng)
        people = call_out_people(self.base, archive_path, group, rng=rng)
        available = ["relatable", "hot_take", "light_question"] + (["callback"] if callbacks else []) + (["call_out"] if people else [])
        if curated_source:
            available.append("share_link")
        shapes = pick_shapes(history, available, PREVIEW_COUNT if manual else int(c.get("proactive_candidates", 3)), rng)
        if curated_source and "share_link" not in shapes:
            shapes[-1] = "share_link"
        if progress:
            progress("正在构思几个不同写法的开场")
        recent_replies = [m["text"] for m in recent[-60:] if m.get("self") and m.get("text")]
        context = recent[-c["context_messages"]:]
        payload = {
            "group": group,
            "current_date": today(),
            "recent_context": context,
            "recent_account_replies": [{"id": m["id"], "text": m["text"]} for m in recent[-60:] if m.get("self") and m.get("text")][-6:],
            "style_examples": load_style_examples(self.base, c, group, recent),
            "style_profile": load_style_profile(self.base, group, c.get("style_profile_max_chars", 1999)),
            "topic_domains": domains,
            "web_sources": curated_source,
            "discussion_angle": discussion_angle,
            "recent_proactive": history,
            "shapes": [{"id": shape, "how": SHAPES[shape]} for shape in shapes],
            "callback_material": callbacks if "callback" in shapes else [],
            "call_out_people": people if "call_out" in shapes else [],
            "avoid_repeating": repeated_patterns(recent_replies + [item.get("text", "") for item in history]),
            "candidates_wanted": len(shapes),
            "manual_trigger": manual,
            **({"declined_candidates": [str(text)[:200] for text in declined][-6:]} if declined else {}),
            **people_field(self.base, {"recent_context": context}),
        }

        def write(retry=False):
            body = {**payload, "avoid_promotional_retry": True} if retry else payload
            result = run("proactive-candidates", body)
            raw = result.get("candidates")
            if not isinstance(raw, list):
                raise RuntimeError("主动话题候选格式无效")
            return self._clean_topics(raw, curated_source, history, shapes)

        candidates, rejected = write()
        if not candidates:
            if progress:
                progress("话题重复或像引流，正在换个角度")
            candidates, again = write(retry=True)
            rejected += again
        if not candidates:
            raise RuntimeError("主动话题重复或疑似引流，已放弃发送" if {"promo", "duplicate"} & set(rejected)
                               else "主动话题不符合长度或格式限制")
        if manual:
            candidates = candidates[:PREVIEW_COUNT]
        if progress:
            progress(f"写好了 {len(candidates)} 个开场，等你来选" if manual else
                     f"写出了 {len(candidates)} 个开场，正在挑最自然的一个" if len(candidates) > 1 else "话题已写好",
                     thoughts=[f"【候选·{item['shape'] or '?'}】{item['reply']}" for item in candidates])
        if manual:
            return {"kind": "proactive_preview", "should_reply": True, "candidates": candidates,
                    "usage": {"input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"]},
                    "seconds": round(totals["seconds"], 2), **totals["used"], "calls": totals["calls"], "topic_domains": domains}
        pick, judge_reason = candidates[0], ""
        if len(candidates) > 1 and c.get("proactive_judge", True):
            try:
                verdict = run("proactive-judge", {
                    "group": group, "recent_context": context, "recent_proactive": history,
                    "style_profile": payload["style_profile"],
                    "candidates": [{"index": i, "shape": item["shape"], "reply": item["reply"]} for i, item in enumerate(candidates)]})
                index = verdict.get("pick")
                if type(index) is int and 0 <= index < len(candidates):
                    pick, judge_reason = candidates[index], str(verdict.get("reason") or "")
            except (RuntimeError, AITimeout) as exc:
                self._event(f"话题评审没有结果，用第一个候选：{str(exc)[:120]}")
        return {"kind": "proactive", "should_reply": True, "reply": pick["reply"], "reason": pick["reason"] or judge_reason,
                "usage": {"input_tokens": totals["input_tokens"], "output_tokens": totals["output_tokens"]},
                "seconds": round(totals["seconds"], 2), **totals["used"],
                "calls": totals["calls"], "topic_domains": domains, "source_url": pick["source_url"],
                "shape": pick["shape"], "candidates": [item["reply"] for item in candidates], "judge_reason": judge_reason}

    def _topic_source(self, group, recent, history, archive_path, progress, run):
        """Domains the group talks about -> search -> one curated outside item. Returns (domains, [source], angle)."""
        c = self.config
        if progress:
            progress("先归纳群聊常见领域")
        domain_history = archived_style_messages(archive_path, group)
        sample_count = min(len(domain_history), 80)
        if sample_count and len(domain_history) > sample_count:
            domain_messages = [domain_history[round(index * (len(domain_history) - 1) / (sample_count - 1))]
                               for index in range(sample_count)]
        else:
            domain_messages = domain_history or recent[-80:]
        topics = run("proactive-domains", {"group": group, "messages": domain_messages,
                                           "style_profile": load_style_profile(self.base, group, c.get("style_profile_max_chars", 1999))})
        domains = topics.get("domains")
        if not isinstance(domains, list) or not all(isinstance(value, str) for value in domains):
            raise RuntimeError("群聊领域总结格式无效")
        domains = [value.strip()[:32] for value in domains if value.strip()][:5]
        queries = topics.get("search_queries", domains[:2])
        if not isinstance(queries, list) or not all(isinstance(value, str) for value in queries):
            raise RuntimeError("主动话题检索词格式无效")
        queries = [value.strip()[:64] for value in queries if value.strip()][:2]
        previous_urls = {item.get("source_url") for item in history if item.get("source_url")}
        if progress:
            progress("正在搜索相关内容和视频")
        sources = [item for item in proactive_source_candidates(queries or domains[:2], c)
                   if item["url"] not in previous_urls and not repeated_proactive_title(item["title"], history)]
        if not sources:
            return domains, [], ""
        if progress:
            progress("正在挑真正值得聊的内容")
        selected = run("proactive-curation", {"group": group, "current_date": today(), "domains": domains, "candidates": sources,
                                               "recent_context": recent[-c["context_messages"]:], "recent_proactive": history})
        url, angle = selected.get("source_url"), selected.get("discussion_angle")
        if not isinstance(url, str) or not isinstance(angle, str):
            raise RuntimeError("主动话题选题格式无效")
        return domains, [item for item in sources if item["url"] == url][:1], angle.strip()[:200]

    def _clean_topics(self, raw, curated_source, history, shapes):
        """Candidates that may be posted, and why the others were rejected ("promo", "duplicate" or "format")."""
        max_chars = self.config["max_reply_chars"]
        allowed, kept, rejected, seen = {item["url"] for item in curated_source}, [], [], set()
        for item in raw[:6]:
            if not isinstance(item, dict):
                continue
            reply = str(item.get("reply") or "").strip()
            reason = str(item.get("reason") or "").strip()
            url = str(item.get("source_url") or "").strip()
            shape = str(item.get("shape") or "").strip()
            if promotional_topic(reply) or promotional_link(url) or link_only_topic(reply, url):
                rejected.append("promo")
                continue
            if repeated_proactive_title(reply, history):
                rejected.append("duplicate")
                continue
            if url and (urllib.parse.urlsplit(url).scheme != "https" or url not in allowed):
                url = ""
            if not url:
                reply = re.sub(r"https?://\S+", "", reply).strip()
            elif url not in reply:
                reply = f"{reply} {url}"
            limit = max_chars + (min(len(url) + 1, 750) if url else 0)
            if not reply or len(reply) > limit or "\n" in reply or "\r" in reply or "@" in reply or reply in seen:
                rejected.append("format")
                continue
            seen.add(reply)
            kept.append({"reply": reply, "reason": reason, "source_url": url, "shape": shape if shape in shapes else ""})
        plain = [item for item in kept if not survey_shaped(item["reply"])]
        return (plain or kept), rejected

    def _generate_reply(self, context, images, style_examples):
        """Decide whether to reply and write the reply in one call."""
        payload = {
            **context,
            "style_examples": style_examples,
            **reply_profile_fields(self.base, self.config, context["group"]),
            "group_context": load_group_context(self.base, self.config, context["group"]),
            **people_field(self.base, context),
        }
        result, usage, seconds = self._ask("reply", payload, images)
        should_reply = result.get("should_reply")
        reason = result.get("reason")
        reply = result.get("reply", "")
        if (type(should_reply) is not bool or not isinstance(reason, str) or not isinstance(reply, str)):
            raise RuntimeError("AI 接口返回格式无效")
        if payload.get("direct_mention") and not should_reply:
            should_reply = True
            reason = "明确 @ 本账号，必须回应"
            if not reply.strip():
                reply = "看到了，不过这条我暂时答不上来。"
        text = " ".join(reply.splitlines()).strip()
        if should_reply and not text:
            if payload.get("direct_mention"):
                text = "看到了，不过这条我暂时答不上来。"
            else:
                raise RuntimeError("AI 回复为空")
        if not should_reply:
            text = ""
        return {"should_reply": should_reply, "reply": text, "reason": reason, "thoughts": usage.get("thoughts", []),
                "usage": usage, "seconds": seconds, "model": self.config["ai"]["model"], "backend": "ai"}
