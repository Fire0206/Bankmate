"""Small deterministic extractors used to validate explicit agent write intent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class SplitIntent:
    title: str | None
    amount_minor: int | None
    participant_names: tuple[str, ...] | None


@dataclass(frozen=True)
class BirthdayPlanIntent:
    birthday_on: date | None
    budget_minor: int | None
    account_label: str | None
    card_suffix: str | None


def is_birthday_status_query(request_text: str) -> bool:
    """Return true for read-only questions about saved birthday plans or orders."""
    request = request_text.casefold()
    if "生日" not in request or not any(
        phrase in request
        for phrase in (
            "查询",
            "查看",
            "状态",
            "进度",
            "已保存",
            "有哪些",
            "列表",
            "到期",
            "提醒",
            "订单",
        )
    ):
        return False
    return not any(
        phrase in request
        for phrase in ("安排", "预留", "创建", "调整", "取消", "购买", "下单", "订购", "确认")
    )


def birthday_plan_intent(request_text: str) -> BirthdayPlanIntent | None:
    """Extract only user-supplied birthday planning fields for tool grounding."""
    if not (
        "生日" in request_text
        and any(item in request_text for item in ("鲜花", "花束"))
        and "蛋糕" in request_text
    ):
        return None
    if not any(item in request_text for item in ("预留", "留出", "预算", "安排", "预约")):
        return None
    date_match = re.search(
        r"(?<!\d)(20\d{2})(?:\s*-\s*|\s*年\s*)(\d{1,2})(?:\s*-\s*|\s*月\s*)(\d{1,2})\s*日?(?!\d)",
        request_text,
    )
    birthday_on = None
    if date_match is not None:
        try:
            birthday_on = date(*map(int, date_match.groups()))
        except ValueError:
            pass
    else:
        month_day = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日(?!\d)", request_text)
        if month_day is not None:
            try:
                today = datetime.now(timezone(timedelta(hours=8))).date()
                month, day = map(int, month_day.groups())
                candidate = date(today.year, month, day)
                birthday_on = candidate if candidate > today else date(today.year + 1, month, day)
            except ValueError:
                pass
    budget_match = re.search(
        r"(?:预留|留出|预算|安排)\s*(\d{1,6}(?:\.\d{1,2})?)\s*(?:元|块钱|块)",
        request_text,
    )
    budget_minor = None
    if budget_match is not None:
        try:
            budget_minor = int(Decimal(budget_match.group(1)) * 100)
        except InvalidOperation:
            pass
    everyday = any(item in request_text for item in ("日常账户", "Everyday account"))
    savings = any(item in request_text for item in ("储蓄账户", "Savings account"))
    account_label = (
        "Everyday account"
        if everyday and not savings
        else "Savings account"
        if savings and not everyday
        else "Everyday account"
    )
    suffix_match = re.search(r"(?:尾号|卡号)\s*(\d{4})", request_text)
    card_suffix = suffix_match.group(1) if suffix_match else None
    return BirthdayPlanIntent(birthday_on, budget_minor, account_label, card_suffix)


_SPLIT_MARKER = re.compile(r"(?:aa\s*)?分账", re.IGNORECASE)
_MONEY = re.compile(r"(?P<amount>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?)\s*(?:元|块钱|块)")
_TITLE_DECLARATION = re.compile(
    r"(?:标题|活动名(?:称)?|名称)\s*"
    r"(?:(?:是|为|叫|[:：])\s*[\"'“「『]?|[\"'“「『])"
    r"([^，,。；;！？!?\"'”」』]+)"
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
_PLAN_ONLY_RE = re.compile(r"(?:只|仅)(?:做|进行)[^。；;！？!?\n]{0,20}(?:测算|规划|方案|计算)")


def is_planning_only_request(request_text: str) -> bool:
    """Identify explicit requests for a plan or calculation without execution."""
    normalized = request_text.casefold()
    return any(phrase in normalized for phrase in _PLAN_ONLY_PHRASES) or bool(
        _PLAN_ONLY_RE.search(normalized)
    )


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
        # “确认后冻结” is a requested next action, unlike “确认是否已冻结”.
        before_clause = re.sub(r"(?:确认|核对|查明)(?:后|之后)\s*$", "", before_clause)
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

    if re.search(
        r"(?:单笔|单日|每日|每天).{0,12}(?:限额|上限)|(?:限额|上限).{0,12}(?:单笔|单日|每日|每天)",
        request,
    ) and re.search(r"(?:改|调|设置|设为|提高|降低|调整)", request):
        return "card.controls"
    if re.search(
        r"(?:开启|打开|允许|恢复|关闭|禁用|停用).{0,15}(?:线上|网络支付|网上支付)|(?:线上|网络支付|网上支付).{0,15}(?:开启|打开|允许|恢复|关闭|禁用|停用)",
        request,
    ):
        return "card.controls"
    if (
        not any(word in request for word in ("生日", "预约", "定时", "计划", "到时候"))
        and re.search(
            r"(?:购买|买|支付).{0,20}(?:鲜花|蛋糕)|(?:鲜花|蛋糕).{0,20}(?:购买|买|支付)", request
        )
        and any(word in request for word in ("卡", "尾号"))
    ):
        return "card.purchase"

    replacement_match = _active_action_match(
        request,
        re.compile(
            r"(?:补卡|补发(?:一张|新|一张新|一张新的|新的)?(?:借记卡|银行卡|新卡|卡)|"
            r"补办(?:一张|新|一张新|一张新的|新的)?(?:借记卡|银行卡|新卡|卡)|"
            r"重新发卡|申请新卡|换(?:一张|张)?新卡)"
        ),
    )
    if replacement_match is not None:
        return "card.replace"

    application_match = _active_action_match(
        request,
        re.compile(r"(?:申请|办)(?:一张|张|个)?(?:模拟)?(?:新的?\s*)?(?:借记卡|银行卡|新卡)"),
    )
    if application_match is not None and not any(
        word in request for word in ("挂失", "补卡", "补发", "补办")
    ):
        return "card.apply"

    # Reporting a card lost is a separate irreversible simulated state. A
    # generic request to unfreeze must never be interpreted as lost-card recovery.
    lost_match = next(
        (
            match
            for pattern in (
                re.compile(
                    r"(?:挂失|报失)(?=[^，,。；;！？!?\n]{0,20}(?:银行卡|卡片|储蓄卡|借记卡|卡|尾号|\d{4}|这张|那张|它|$))"
                ),
                re.compile(r"(?:帮我|请|麻烦|替我|为我|我要|需要).{0,12}(?:挂失|报失)"),
                re.compile(
                    r"(?:银行卡|卡片|储蓄卡|借记卡|尾号\s*\d{4}|这张卡|那张卡).{0,12}(?:挂失|报失)"
                ),
            )
            if (match := _active_action_match(request, pattern)) is not None
        ),
        None,
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
        phrase in request
        for phrase in ("自动扣费", "自动续费", "订阅", "会员", "续费", "代扣", "扣费")
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
        r"(?:暂停|暂时停|临时停|先停一下|暂时停止|临时停止)(?:.{0,16})(?:自动扣费|自动续费|订阅|会员|续费|扣款|代扣|扣费)"
        r"|(?:自动扣费|自动续费|订阅|会员|续费|扣款|代扣|扣费)(?:[^，,。；;！？!?\n]{0,12})(?:暂停|暂时停|临时停|先停一下)"
    )
    pause = _active_action_match(request, pause_pattern)
    if pause is not None and not re.search(r"暂停(?:中|状态|过|后|之后)", request):
        return "subscription.pause"
    return None


def is_subscription_reminder_query(request_text: str) -> bool:
    """Distinguish reminder/date questions from a subscription inventory request."""
    request = request_text.casefold()
    has_subscription_scope = any(
        phrase in request
        for phrase in ("自动扣费", "自动续费", "订阅", "会员", "续费", "代扣", "扣费")
    )
    asks_about_timing = any(
        phrase in request
        for phrase in (
            "提醒",
            "到期",
            "临近",
            "即将",
            "快要",
            "下次扣",
            "什么时候扣",
            "什么时候续费",
            "什么时候到期",
            "何时扣",
            "何时续费",
            "何时到期",
            "哪天扣",
            "哪天续费",
            "扣费时间",
            "续费日期",
            "续费时间",
        )
    )
    return (
        has_subscription_scope
        and asks_about_timing
        and requested_subscription_tool(request_text) is None
    )


def is_annual_bill_query(request_text: str) -> bool:
    """Recognize annual statement phrasing across common year and period forms."""
    request = request_text.casefold()
    has_annual_period = (
        any(
            phrase in request
            for phrase in ("年度", "全年", "去年", "前年", "上一年", "上一年度", "过去一年", "整年")
        )
        or re.search(r"(?<!\d)20\d{2}\s*年", request) is not None
    )
    has_financial_scope = any(
        phrase in request for phrase in ("账单", "收支", "流水", "账目", "消费", "支出", "收入")
    )
    return has_annual_period and has_financial_scope


def has_explicit_transfer_write_intent(request_text: str) -> bool:
    """Recognize transfer execution commands, not transfer history or status queries."""
    request = request_text.casefold()
    if requested_card_tool(request_text) in {"card.controls", "card.purchase"}:
        return False
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
    if requested_card_tool(request_text) == "card.purchase":
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
        title = _clean_title(title_match.group(1), explicit=True)
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


def _clean_title(value: str, *, explicit: bool = False) -> str | None:
    title = value.strip(" \t\r\n:：,，、-—的\"'“”‘’「」『』")
    title = re.sub(r"\s+", " ", title)
    if not title or len(title) > 120:
        return None
    if not explicit and re.search(r"(?:分账|平分|均分|对半|各出|AA)$", title, re.IGNORECASE):
        return None
    return title
