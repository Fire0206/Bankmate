"""Small deterministic extractors used to validate explicit agent write intent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class SplitIntent:
    title: str | None
    amount_minor: int | None
    participant_names: tuple[str, ...] | None


_SPLIT_MARKER = re.compile(r"(?:aa\s*)?分账", re.IGNORECASE)
_MONEY = re.compile(r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\s*(?:元|块钱|块)")
_TITLE_DECLARATION = re.compile(
    r"(?:标题|名称|活动名)\s*(?:是|为|叫|[:：])\s*[\"'“「『]?([^，,。；;！？!?\"'”」』]+)"
)
_TITLE_PREFIX = re.compile(
    r"^(?:(?:麻烦|请)?(?:帮我|给我)?(?:创建|新建|建立|发起|安排|做|开|收取|收款|催收)"
    r"\s*(?:一个|一笔|个)?\s*)+"
)
_PARTICIPANT_INTRO = re.compile(
    r"(?:参与人(?:包括|是|有)?|参与者(?:包括|是|有)?|和|与|同|跟|由)\s*"
)
_PARTICIPANT_END = re.compile(
    r"平分|均分|平均分|对半|分摊|各出|每人|总金额|总额|金额|共计|一起|参与|参加|AA|分账",
    re.IGNORECASE,
)
_PLAN_ONLY_PHRASES = (
    "只做方案",
    "只做测算",
    "只做规划",
    "只计算",
    "只测算",
    "只规划",
    "仅做方案",
    "仅做测算",
    "仅做规划",
    "仅计算",
    "仅测算",
    "仅规划",
    "先不执行",
    "暂不执行",
    "不要执行",
    "不需要执行",
    "只给建议",
    "先只规划",
)


def is_planning_only_request(request_text: str) -> bool:
    """Identify explicit requests for a plan or calculation without execution."""
    normalized = request_text.casefold()
    return any(phrase in normalized for phrase in _PLAN_ONLY_PHRASES)


def parse_split_intent(request_text: str) -> SplitIntent:
    """Extract only explicitly stated split fields; leave uncertain fields unset."""
    marker = _SPLIT_MARKER.search(request_text)
    if marker is None:
        return SplitIntent(None, None, None)

    title_match = _TITLE_DECLARATION.search(request_text)
    title: str | None = None
    if title_match is not None:
        title = _clean_title(title_match.group(1))
    else:
        prefix = request_text[: marker.start()]
        amounts_before_marker = list(_MONEY.finditer(prefix))
        if amounts_before_marker:
            candidate = prefix[amounts_before_marker[-1].end() :]
        else:
            candidate = prefix
        candidate = _TITLE_PREFIX.sub("", candidate.strip())
        candidate = candidate.strip(" \t\r\n:：,，、-—的")
        title = _clean_title(candidate)

    money_matches = list(_MONEY.finditer(request_text))
    amount_minor: int | None = None
    if money_matches:
        nearest = min(money_matches, key=lambda item: abs(item.start() - marker.start()))
        try:
            amount_minor = int(Decimal(nearest.group("amount").replace(",", "")) * 100)
        except (InvalidOperation, ValueError, OverflowError):
            amount_minor = None

    tail = request_text[marker.end() :]
    participant_intro = _PARTICIPANT_INTRO.search(tail)
    participant_names: tuple[str, ...] | None = None
    if participant_intro is not None:
        segment = tail[participant_intro.end() :]
        segment = re.split(r"[，,。；;！？!?\n]", segment, maxsplit=1)[0]
        segment = _PARTICIPANT_END.split(segment, maxsplit=1)[0]
        names = [
            item.strip(" \t\r\n:：、-—")
            for item in re.split(r"[、,，和与及]", segment)
            if item.strip(" \t\r\n:：、-—")
        ]
        names = [name for name in names if name not in {"我", "自己", "大家", "朋友", "同事"}]
        if names and len(names) <= 10 and len(set(names)) == len(names):
            participant_names = tuple(names)

    return SplitIntent(title, amount_minor, participant_names)


def _clean_title(value: str) -> str | None:
    title = value.strip(" \t\r\n:：,，、-—的\"'“”‘’「」『』")
    title = re.sub(r"\s+", " ", title)
    if not title or len(title) > 120:
        return None
    if re.search(r"(?:分账|平分|均分|对半|各出|AA)$", title, re.IGNORECASE):
        return None
    return title
