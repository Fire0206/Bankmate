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
_TITLE_COMMAND_PREFIX = re.compile(r"^(?:(?:麻烦|请)?(?:帮我|给我)?(?:把|将))\s*")
_TITLE_COMMAND_SUFFIX = re.compile(r"(?:记作|记为|作为|命名为|定名为|叫做|称作)\s*$")
_PARTICIPANT_END = re.compile(
    r"平分|均分|平均分|对半|分摊|各出|每人|总金额|总额|金额|合计|共计|一起|参与|参加|AA|分账",
    re.IGNORECASE,
)
_PARTICIPANT_PATTERNS = (
    re.compile(
        r"参与(?:者|人)\s*(?:包括|是|为|有|名单为|名单是)?\s*(?P<names>[^。；;！？!?\n]{1,100})"
    ),
    re.compile(
        r"除(?:我|本人)(?:之外|以外)(?:还)?\s*(?:有|包括|是)?\s*(?P<names>[^。；;！？!?\n]{1,100})"
    ),
    re.compile(r"由\s*(?P<names>[^。；;！？!?\n]{1,100}?)(?:参与|参加|分摊|平分|均分)"),
    re.compile(
        r"(?:和|与|跟)\s*(?P<names>[^。；;！？!?\n]{1,100}?)(?:平分|均分|平均分|对半|分摊|各出|每人)"
    ),
    re.compile(r"(?:^|[，,；;])\s*(?:和|与|跟)\s*(?P<names>[^。；;！？!?\n]{1,100})"),
)
_PARTICIPANT_SPLIT = re.compile(r"[、,，/和与及]")
_TOTAL_AMOUNT_MARKER = re.compile(
    r"(?:总金额|总额|合计|共计|一共|总计|总共|合共)\s*(?:是|为|[:：])?\s*$"
)
_PER_PERSON_AMOUNT = re.compile(
    r"(?:每人|每位|每个(?:人|参与者|参与人)?|人均|各自|各出)\s*(?:出|支付|承担|摊)?\s*$"
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


def _has_query_cue(text: str) -> bool:
    return any(
        cue in text
        for cue in (
            "怎么",
            "怎样",
            "如何",
            "哪些",
            "什么",
            "是否",
            "能否",
            "可以吗",
            "能不能",
            "查询",
            "查看",
            "列出",
            "状态",
            "历史",
            "记录",
            "有没有",
            "是什么",
            "有什么区别",
        )
    )


def _active_action_match(text: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    """Find an action verb not used as a negation, historical state, or query."""
    for match in pattern.finditer(text):
        before = text[max(0, match.start() - 20) : match.start()]
        before_clause = re.split(r"[，,。；;！？!?\n]|然后|随后|接着|再|并且|并|同时", before)[-1]
        if re.search(r"(?:不要|别|不必|无需|不需要|保持|维持|继续|已经|已|被|处于)\s*$", before):
            continue
        if re.search(
            r"(?:查看|查询|了解|核实|确认|问问|想知道|怎么|怎样|如何|哪些|什么|是否|能否|列出|状态|历史|记录|有没有).{0,12}$",
            before_clause,
        ):
            continue
        return match
    return None


def requested_card_tool(request_text: str) -> str | None:
    """Return only a direct card-state change request, excluding state descriptions."""
    request = request_text.casefold()
    if is_planning_only_request(request):
        return None

    # Reporting a card lost is a separate irreversible simulated state. A
    # generic request to unfreeze must never be interpreted as lost-card recovery.
    lost_match = _active_action_match(
        request,
        re.compile(
            r"(?:挂失|报失)(?=[^，,。；;！？!?\n]{0,20}(?:银行卡|卡片|储蓄卡|借记卡|卡|尾号|\d{4}|这张|那张|它|$))"
        ),
    )
    if lost_match is not None:
        return "card.report_lost"

    restore_patterns = (
        re.compile(r"(?:解除|撤销|取消)(?:掉)?[^，,。；;！？!?\n]{0,24}(?:冻结|锁定)"),
        re.compile(
            r"(?:解冻)(?=[^，,。；;！？!?\n]{0,16}(?:银行卡|卡片|储蓄卡|借记卡|卡|尾号|\d{4}|这张|那张|它|$))"
        ),
        re.compile(
            r"(?:恢复|重新启用|重新开通)[^，,。；;！？!?\n]{0,24}(?:银行卡|卡片|储蓄卡|借记卡|卡|使用|刷卡|冻结状态|正常使用)"
        ),
        re.compile(r"(?:从|由)(?:已|当前)?冻结状态[^，,。；;！？!?\n]{0,12}(?:恢复|解冻|启用)"),
    )
    freeze_patterns = (
        re.compile(
            r"(?:冻结|锁卡|锁上|锁住|锁定)(?=[^，,。；;！？!?\n]{0,16}(?:银行卡|卡片|储蓄卡|借记卡|卡|尾号|\d{4}|这张|那张|它))"
        ),
        re.compile(
            r"(?:请|麻烦|帮我|替我|给我|我要|我想|需要|要)(?:把|将)?[^，,。；;！？!?\n]{0,16}(?:冻结|锁卡|锁上|锁住|锁定)"
        ),
        re.compile(r"(?:把|将)[^，,。；;！？!?\n]{0,24}(?:冻结|锁卡|锁上|锁住|锁定)"),
    )
    actions: list[tuple[int, str]] = []
    for pattern in restore_patterns:
        match = _active_action_match(request, pattern)
        if match is not None:
            actions.append((match.start(), "card.unfreeze"))
    for pattern in freeze_patterns:
        match = _active_action_match(request, pattern)
        if match is not None:
            actions.append((match.start(), "card.freeze"))

    if not actions:
        return None
    return max(actions, key=lambda item: item[0])[1]


def requested_subscription_tool(request_text: str) -> str | None:
    """Return a direct subscription operation, ignoring past state and future options."""
    request = request_text.casefold()
    if not any(
        phrase in request for phrase in ("自动扣费", "自动续费", "订阅", "会员", "续费", "代扣")
    ):
        return None
    if is_planning_only_request(request):
        return None

    future_restore = re.search(
        r"(?:以后|之后|稍后|将来|随时|可以|可|能够|还能|能再).{0,8}恢复|"
        r"恢复.{0,8}(?:可以|可|能够|还能|能再)",
        request,
    )

    resume_pattern = re.compile(
        r"(?:恢复|重新(?:开启|开通|启用))(?:.{0,18})(?:自动扣费|自动续费|订阅|会员|续费|扣款|正常)"
        r"|继续(?:自动扣费|自动续费|订阅|会员|续费|扣款|正常)"
        r"|(?:自动扣费|自动续费|订阅|会员|续费|扣款)(?:.{0,12})(?:恢复|重新开启|重新启用)"
    )
    cancel_pattern = re.compile(
        r"(?:取消|停止|关闭|关掉|永久关闭)(?:掉)?(?:.{0,16})(?:自动扣费|自动续费|订阅|会员|續费|续费|扣款)"
        r"|(?:自动扣费|自动续费|订阅|会员|续费|扣款)(?:.{0,12})(?:取消|停止|关闭|关掉)"
    )
    cancel = _active_action_match(request, cancel_pattern)
    temporal_query = re.search(
        r"(?:取消|暂停|恢复)(?:之后|以后|后).{0,16}(?:查看|查询|历史|记录|状态)", request
    )
    if cancel is not None and temporal_query is None:
        return "subscription.cancel"

    resume = _active_action_match(request, resume_pattern)
    if resume is not None and future_restore is None:
        return "subscription.resume"

    pause_pattern = re.compile(
        r"(?:暂停|暂时停|临时停|先停一下|暂时停止|临时停止)(?:.{0,16})(?:自动扣费|自动续费|订阅|会员|续费|扣款|代扣)"
        r"|(?:自动扣费|自动续费|订阅|会员|续费|扣款|代扣)(?:[^，,。；;！？!?\n]{0,12})(?:暂停|暂时停|临时停|先停一下)"
    )
    pause = _active_action_match(request, pause_pattern)
    if pause is not None and not re.search(r"暂停(?:中|状态|过|后|之后)", request):
        return "subscription.pause"
    return None


def has_explicit_transfer_write_intent(request_text: str) -> bool:
    """Recognize transfer execution commands, not transfer history or status queries."""
    request = request_text.casefold()
    if is_planning_only_request(request):
        return False
    action = re.compile(
        r"(?:请|麻烦|帮我|替我|给我|我要|我想|把|将|创建|安排|预约|定时)(?:.{0,16})"
        r"(?:转账|转给|转钱|转一部分|支付|汇款|打款|划转|预约付款|定时转)"
        r"|(?:转给|给)\s*[\u4e00-\u9fffA-Za-z0-9]{1,12}\s*(?:转账?|支付|汇款|打款|\d|一部分)"
        r"|(?:转账?|支付|汇款|打款|划转)\s*\d+(?:\.\d{1,2})?\s*(?:元|块钱|块)"
        r"|给\s*[^，。！？；,;]{1,16}转(?:账)?"
    )
    return _active_action_match(request, action) is not None


def has_explicit_investment_write_intent(request_text: str) -> bool:
    """Recognize a buy/redeem command; product and risk questions remain read-only."""
    request = request_text.casefold()
    if is_planning_only_request(request):
        return False
    action = re.compile(
        r"(?:申购|买入|购买|买|赎回)(?:.{0,18})(?:产品|理财|基金|[\u4e00-\u9fff]|\d|全部|剩余|余款|它|该产品)"
        r"|(?:把|将|用)?(?:.{0,8})(?:剩余|余下|其余|余款|可用资金|全部资金)(?:.{0,16})(?:投资|投入|申购|买入|购买|买)"
        r"|(?:按|根据)?(?:可投金额|可投资金额)(?:.{0,12})(?:配置|申购|买入|购买|投资)"
        r"|配置(?:.{0,16})(?:可投金额|适合产品|理财产品)"
        r"|安排(?:.{0,8})(?:模拟)?理财"
        r"|(?:投资|申购|买入|购买)\s*\d+(?:\.\d{1,2})?\s*(?:元|块钱|块)"
    )
    return _active_action_match(request, action) is not None


def is_split_creation_request(request_text: str) -> bool:
    """Recognize a request to create a split, not a query about existing splits."""
    request = request_text.casefold()
    if not _SPLIT_MARKER.search(request) or is_planning_only_request(request):
        return False
    explicit = re.search(r"(?:创建|新建|建立|发起|安排|开一笔|做一笔|记作|记为)", request)
    if explicit is None:
        return False
    if re.search(
        r"^(?:怎么|如何|怎样|能否|是否|哪些|查看|查询|列出).{0,12}(?:创建|新建|建立|发起)",
        request,
    ):
        return False
    has_query_cue = any(cue in request for cue in ("查询", "查看", "列出", "历史", "当前状态"))
    has_explicit_command = re.search(
        r"(?:请|麻烦|帮我|我要|我想|建立|创建|发起|安排|记作|记为)",
        request,
    )
    if has_query_cue and not has_explicit_command:
        return False
    return True


def parse_split_intent(request_text: str) -> SplitIntent:
    """Extract only explicit split fields; per-person amounts are not total amounts."""
    marker = _SPLIT_MARKER.search(request_text)
    if marker is None:
        return SplitIntent(None, None, None)

    title_match = _TITLE_DECLARATION.search(request_text)
    title: str | None = None
    if title_match is not None:
        title = _clean_title(title_match.group(1))
    else:
        prefix = request_text[: marker.start()]
        money_before = [item for item in _MONEY.finditer(prefix)]
        candidate = prefix[money_before[-1].end() :] if money_before else prefix
        candidate = _TITLE_COMMAND_PREFIX.sub("", candidate.strip())
        candidate = _TITLE_PREFIX.sub("", candidate.strip())
        candidate = _TITLE_COMMAND_SUFFIX.sub("", candidate.strip())
        candidate = candidate.strip(" \t\r\n:：,，、-—的")
        title = _clean_title(candidate)

    money_matches = list(_MONEY.finditer(request_text))
    total_candidates: list[tuple[re.Match[str], bool]] = []
    for item in money_matches:
        before = request_text[max(0, item.start() - 16) : item.start()]
        if _PER_PERSON_AMOUNT.search(before):
            continue
        total_candidates.append((item, bool(_TOTAL_AMOUNT_MARKER.search(before))))
    marked_totals = [item for item, marked in total_candidates if marked]
    selected_amount = marked_totals[0] if len(marked_totals) == 1 else None
    if selected_amount is None and not marked_totals and len(total_candidates) == 1:
        selected_amount = total_candidates[0][0]
    amount_minor: int | None = None
    if selected_amount is not None:
        try:
            amount_minor = int(Decimal(selected_amount.group("amount").replace(",", "")) * 100)
        except (InvalidOperation, ValueError, OverflowError):
            amount_minor = None

    participant_names: tuple[str, ...] | None = None
    for pattern in _PARTICIPANT_PATTERNS:
        match = pattern.search(request_text)
        if match is None:
            continue
        segment = _PARTICIPANT_END.split(match.group("names"), maxsplit=1)[0]
        names = [
            item.strip(" \t\r\n:：、-—")
            for item in _PARTICIPANT_SPLIT.split(segment)
            if item.strip(" \t\r\n:：、-—")
        ]
        names = [
            name
            for name in names
            if name not in {"我", "本人", "自己", "当前用户", "大家", "朋友", "朋友们", "同事"}
        ]
        if names and len(names) <= 10 and len(set(names)) == len(names):
            participant_names = tuple(names)
        break

    return SplitIntent(title, amount_minor, participant_names)


def _clean_title(value: str) -> str | None:
    title = value.strip(" \t\r\n:：,，、-—的\"'“”‘’「」『』")
    title = re.sub(r"\s+", " ", title)
    if not title or len(title) > 120:
        return None
    if re.search(r"(?:分账|平分|均分|对半|各出|AA)$", title, re.IGNORECASE):
        return None
    return title
