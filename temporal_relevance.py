"""Check whether a source date can support a current claim."""
from datetime import datetime
from email.utils import parsedate_to_datetime
import re
from zoneinfo import ZoneInfo


CHAT_TIMEZONE = ZoneInfo("Asia/Shanghai")


CURRENT_WORDS = re.compile(r"现在|目前|今天|近日|最近|近期|本周|本月|今年|最新|当下|正在|还在|即将|现已|today|current(?:ly)?|latest|upcoming", re.I)
CHANGING_TOPICS = re.compile(r"活动|赛季|卡池|复刻|联动|版本|更新|补丁|维护|停服|上线|开服|兑换码|价格|售价|发售|上映|直播|比赛|event|season|banner|patch|release|price", re.I)
HISTORICAL_WORDS = re.compile(r"历史|回顾|复盘|考古|当年|以前|过去|旧版|往期|历年|机制|原理|设定|剧情|教程|攻略|解析|评测|实测|history|retrospective|explained|guide|review", re.I)
ANNOUNCEMENT_WORDS = re.compile(r"开启|开幕|开售|上线|发布|开始|登场|推出|即将|进行中|现已|launch(?:ed)?|now live", re.I)


def today():
    return datetime.now(CHAT_TIMEZONE).date().isoformat()


def needs_current_source(text):
    text = str(text or "")
    if HISTORICAL_WORDS.search(text) and not CURRENT_WORDS.search(text):
        return False
    return bool(CURRENT_WORDS.search(text) or CHANGING_TOPICS.search(text))


def source_date(value):
    if not value:
        return None
    value = str(value).strip()
    try:
        if re.fullmatch(r"\d{8}", value):
            return datetime.strptime(value, "%Y%m%d").date()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return parsedate_to_datetime(value).date()
        except (TypeError, ValueError, IndexError):
            return None


def outdated_for_current_claim(request, published, title="", *, now=None, max_age_days=90,
                               include_title_announcements=True):
    title = str(title or "")
    current_announcement = (CHANGING_TOPICS.search(title) and
                            (CURRENT_WORDS.search(title) or ANNOUNCEMENT_WORDS.search(title)) and
                            not HISTORICAL_WORDS.search(title))
    if not (needs_current_source(request) or (include_title_announcements and current_announcement)):
        return False
    published_date = source_date(published)
    if published_date is None:
        return False
    return ((now or datetime.now(CHAT_TIMEZONE).date()) - published_date).days > max_age_days
