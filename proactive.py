"""Proactive topics: source search, promotion filters, history, writing shapes, timing and how topics were received."""
from __future__ import annotations
import html
import json
import os
import random
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from people import load_people
from style import tail_group_records
from temporal_relevance import outdated_for_current_claim
import fsutil


PROMOTIONAL_TOPIC = re.compile(
    r"(?:立即|点击|快来)(?:下载|购买|预约|领取|关注|订阅|加入)|"
    r"(?:扫码|加群|私信我|关注我|点进链接|戳链接)|"
    r"(?:优惠券|领券|推广码|邀请码|返利|下单|带货|商单|广告合作|商务合作|赞助播出)"
)


def promotional_topic(text):
    return bool(PROMOTIONAL_TOPIC.search(text or ""))


def promotional_link(url):
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url or "").query)
    return bool({"affiliate", "aff", "referral", "invite", "coupon", "promo_code"} & query.keys())


def link_only_topic(reply, url):
    if not url:
        return False
    text = str(reply or "").replace(url, "").strip()
    text = re.sub(r"https?://\S+", "", text).strip(" ：:，,。!！?？（）()[]")
    return len(text) < 8


def proactive_history(base, group, limit=12):
    path = base / "runtime/proactive-history.jsonl"
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in records if item.get("group") == group][-limit:]


def record_proactive(base, job):
    path = base / "runtime/proactive-history.jsonl"
    record = {"group": job["group"], "text": job.get("full_text") or job["text"], "source_url": job.get("source_url", ""),
              "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if job.get("shape"):
        record["shape"] = job["shape"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    os.chmod(path, 0o600)


def repeated_proactive_title(text, history):
    previous_titles = {title for item in history for title in re.findall(r"《([^》]{2,40})》", item.get("text", ""))}
    return any(f"《{title}》" in text or title in text for title in previous_titles)


def proactive_source_candidates(queries, config):
    candidates = []
    search = config.get("proactive_search", {})
    for query in [str(item).strip()[:64] for item in queries[:2] if isinstance(item, str) and item.strip()]:
        if search.get("news_rss", True):
            params = urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
            request = urllib.request.Request("https://news.google.com/rss/search?" + params,
                                             headers={"User-Agent": "QQChatBridge/1.0"})
            try:
                with urllib.request.urlopen(request, timeout=12) as response:
                    root = ET.fromstring(response.read(1_000_000))
                for item in root.findall("./channel/item")[:4]:
                    title = (item.findtext("title") or "").strip()
                    link = (item.findtext("link") or "").strip()
                    description = re.sub(r"<[^>]+>", " ", html.unescape(item.findtext("description") or ""))
                    description = " ".join(description.split())[:500]
                    published = (item.findtext("pubDate") or "")[:80]
                    if (title and not promotional_topic(title) and not promotional_link(link)
                            and not outdated_for_current_claim(query, published, title)
                            and link.startswith("https://news.google.com/") and len(link) <= 700):
                        candidates.append({"kind": "news", "title": title[:180], "url": link,
                                           "description": description, "published": published})
            except (OSError, ET.ParseError, urllib.error.URLError):
                pass
        if search.get("youtube", True):
            configured = search.get("yt_dlp")
            executable = configured or shutil.which("yt-dlp") or ""
            if executable and Path(executable).is_file():
                try:
                    result = subprocess.run([executable, "--no-warnings", "--ignore-errors", "--dump-json",
                                             f"ytsearch4:{query}"], capture_output=True, text=True,
                                            encoding="utf-8", errors="replace", timeout=25, check=False,
                                            creationflags=fsutil.no_console())
                    for line in result.stdout.splitlines()[:4]:
                        try:
                            video = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        url = video.get("webpage_url") or video.get("url", "")
                        published = str(video.get("upload_date", ""))[:8]
                        title = str(video.get("title", ""))[:180]
                        if (url.startswith("https://www.youtube.com/watch?v=") and not promotional_topic(title)
                                and not outdated_for_current_claim(query, published, title)
                                and not promotional_link(url)):
                            candidates.append({"kind": "video", "title": title,
                                               "url": url[:300], "description": str(video.get("description", ""))[:500],
                                               "channel": str(video.get("channel", ""))[:100],
                                               "published": published, "views": video.get("view_count")})
                except (OSError, subprocess.TimeoutExpired):
                    pass
    videos = sorted((item for item in candidates if item["kind"] == "video"),
                    key=lambda item: item.get("views") or 0, reverse=True)
    news = [item for item in candidates if item["kind"] == "news"]
    return (news[:6] + videos[:6])[:12]


# -- how a topic is written: shapes -------------------------------------------------------------------------------
# A member who starts a conversation rarely asks a poll. The shape of each topic is chosen here (not by the model, which
# keeps falling back to the same "你们……还是……" question) and rotated so two topics in a row never look alike.
SHAPES = {
    "relatable": "说一个大家多半都遇到过的小尴尬、小毛病或小习惯（用“有没有”“每次”“总是”这类泛指说法，不要说成你自己刚经历的事），让人想接一句“我也是”；一两句，可以不带问号",
    "callback": "接着群里以前聊过的一件具体的事或梗（从 callback_material 里挑一个），问一句后来怎么样了，或者把那个梗再玩一下；不要整句照搬原话",
    "hot_take": "抛一个轻松的小暴论或偏见，让人忍不住想反驳一句；一句话，不要加“你们觉得呢”“大家怎么看”这类收尾",
    "call_out": "对 call_out_people 里的一位熟人说一句只有熟人之间才会说的话（关心、调侃，或追问他最近在玩的东西）；用 name 称呼他，不要 @，不要透露或复述 about 的内容",
    "light_question": "问一个具体的小问题，问某件具体的东西或某个具体的情景；不是泛泛的二选一问卷，不要用“你们……还是……”句式",
    "share_link": "分享 web_sources 里的那条内容：说出其中一个具体、有意思的点，再顺口带一句看法或问题；source_url 逐字使用候选链接",
}
SHAPE_WEIGHTS = {"relatable": 3, "callback": 3, "hot_take": 2, "call_out": 1, "light_question": 2, "share_link": 3}
PREVIEW_COUNT = 3                        # openings offered when the owner presses 主动发起话题 (he picks one, or none)


def pick_shapes(history, available, count=3, rng=None):
    """``count`` different shapes out of ``available`` (weighted). The shapes of the last two topics are skipped while
    enough others remain."""
    rng = rng or random
    recent = [item.get("shape") for item in history[-2:] if item.get("shape")]
    pool = [shape for shape in available if shape not in recent]
    if len(pool) < min(count, len(available)):
        pool = list(available)
    chosen = []
    while pool and len(chosen) < count:
        shape = rng.choices(pool, [SHAPE_WEIGHTS.get(item, 1) for item in pool])[0]
        chosen.append(shape)
        pool.remove(shape)
    return chosen


def _human_rows(path, group, limit):
    return [row for row in tail_group_records(path, group, limit)
            if not row.get("self") and not row.get("bot") and row.get("image_kind") != "sticker"]


def _epoch(row):
    try:
        return time.mktime(time.strptime(row["received_at"], "%Y-%m-%d %H:%M:%S"))
    except (KeyError, ValueError, TypeError):
        return None


def callback_material(path, group, now=None, count=6, rng=None):
    """Things members said one to two weeks ago that are worth calling back to: not too short, no links or @."""
    rng, now = rng or random, time.time() if now is None else now
    pool = []
    for row in _human_rows(path, group, 5000):
        text = " ".join(str(row.get("text", "")).split())
        when = _epoch(row)
        if when is None or not 10 <= len(text) <= 60 or "http" in text.lower() or "@" in text:
            continue
        age = (now - when) / 86400
        if 1 <= age <= 14:
            pool.append({"sender": str(row.get("sender", "")), "text": text, "days_ago": round(age)})
    return rng.sample(pool, min(count, len(pool)))


def call_out_people(base, path, group, now=None, count=2, rng=None):
    """Members who have a note and spoke within the last three days: {"name": how to address them, "about": background}."""
    rng, now = rng or random, time.time() if now is None else now
    recent = {str(row.get("sender", "")) for row in _human_rows(path, group, 3000) if (_epoch(row) or 0) >= now - 3 * 86400}
    found = []
    for person in load_people(base):
        names = [name for name in person.get("names", []) if name]
        if names and any(name in recent for name in names) and (person.get("call_as") or person.get("about")):
            found.append({"name": person.get("call_as") or names[0], "about": str(person.get("about", ""))[:60]})
    return rng.sample(found, min(count, len(found)))


# -- when to post -------------------------------------------------------------------------------------------------
_profile_cache = {}


def hour_profile(path, group, now=None):
    """Messages per hour of the day (local clock, like the archive's own timestamps) from the members of ``group``,
    over the last 30 days. Cached for ten minutes."""
    now = time.time() if now is None else now
    cached = _profile_cache.get((str(path), group))
    if cached and now - cached[0] < 600:
        return cached[1]
    counts = [0] * 24
    for row in _human_rows(path, group, 20000):
        when = _epoch(row)
        if when is not None and when >= now - 30 * 86400:
            counts[time.localtime(when).tm_hour] += 1
    _profile_cache[(str(path), group)] = (now, counts)
    return counts


def hour_is_alive(counts, hour, min_share=0.25, min_total=200):
    """Is ``hour`` a time when this group usually talks? True when there is not enough data to tell."""
    if sum(counts) < min_total or max(counts) <= 0:
        return True
    return counts[hour] >= min_share * max(counts)


def topics_sent_today(base, group, now=None):
    today = time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))
    return sum(1 for item in proactive_history(base, group, limit=60) if str(item.get("at", "")).startswith(today))


def _state_path(base):
    return Path(base) / "runtime/proactive-state.json"


def load_topic_state(base, group):
    try:
        return dict(json.loads(_state_path(base).read_text(encoding="utf-8")).get(group, {}))
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}


def save_topic_state(base, group, state):
    path = _state_path(base)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data = data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[group] = state
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    fsutil.replace(tmp, path)


# -- how a topic was received -------------------------------------------------------------------------------------
def outcomes_path(base):
    return Path(base) / "runtime/proactive-outcomes.json"


def load_outcomes(base):
    try:
        data = json.loads(outcomes_path(base).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_outcome(base, key, record):
    data = load_outcomes(base)
    data[key] = record
    for old in sorted(data, key=lambda k: data[k].get("time", 0))[:-400]:
        del data[old]
    tmp = outcomes_path(base).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.chmod(tmp, 0o600)
    fsutil.replace(tmp, outcomes_path(base))


def topic_label(reactions, people, good_reactions=5):
    """A topic that drew at least ``good_reactions`` messages from two or more people was received well; one that drew
    nothing was ignored; anything in between says little."""
    if reactions >= good_reactions and people >= 2:
        return "good"
    return "bad" if reactions == 0 else "neutral"

