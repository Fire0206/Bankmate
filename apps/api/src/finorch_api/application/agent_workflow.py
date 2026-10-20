import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.agent.intent import (
    _has_query_cue,
    has_explicit_investment_write_intent,
    has_explicit_transfer_write_intent,
    is_planning_only_request,
    is_split_creation_request,
    parse_split_intent,
)
from finorch_api.agent.intent import (
    requested_card_tool as _requested_card_tool,
)
from finorch_api.agent.intent import (
    requested_subscription_tool as _requested_subscription_tool,
)
from finorch_api.infrastructure.models import AgentTask, TaskStep, ToolExecution


def _has_social_engineering_risk_signal(request: str) -> bool:
    signals = (
        "被催",
        "催着",
        "逼我",
        "威胁",
        "保密",
        "不要告诉",
        "不用核实",
        "不用再核实",
        "不需要核实",
        "绕过确认",
        "跳过确认",
        "别弹确认",
        "安全账户",
        "网恋对象",
        "陌生投资顾问",
    )
    return any(signal in request for signal in signals)


def task_progress_context(session: Session, *, actor_id: UUID, task_id: UUID) -> dict[str, Any]:
    task = session.scalar(
        select(AgentTask).where(AgentTask.id == task_id, AgentTask.actor_id == actor_id)
    )
    if task is None:
        return {"task_progress": {"status": "unavailable", "tools": []}}

    rows = session.execute(
        select(TaskStep, ToolExecution)
        .join(ToolExecution, ToolExecution.step_id == TaskStep.id)
        .where(TaskStep.task_id == task_id)
        .order_by(TaskStep.sequence)
    )
    tools = [
        {
            "tool_name": execution.tool_name,
            "sequence": step.sequence,
            "status": execution.status,
            "result_data": execution.result_data if execution.status == "succeeded" else None,
            "error_code": execution.error_code,
        }
        for step, execution in rows
    ]
    return {
        "task_progress": {
            "status": task.status,
            "tools": tools[-24:],
        }
    }


def has_completed_tool_execution(session: Session, *, task_id: UUID) -> bool:
    return (
        session.scalar(
            select(ToolExecution.id)
            .where(ToolExecution.task_id == task_id, ToolExecution.status == "succeeded")
            .limit(1)
        )
        is not None
    )


def invalid_tool_input_name(task_progress: dict[str, Any]) -> str | None:
    for item in reversed(task_progress.get("tools", [])):
        if (
            isinstance(item, dict)
            and item.get("status") == "failed"
            and item.get("error_code") == "tool_input_invalid"
            and isinstance(item.get("tool_name"), str)
        ):
            return item["tool_name"]
    return None


def tool_input_clarification_message(tool_name: str) -> str:
    if tool_name == "finance.payday_plan":
        return "请补充或核对收款人、转账金额和账户预留金额。"
    if tool_name in {"transfer.create", "transfer.schedule"}:
        return "请补充或核对收款人、转账金额和转出账户。"
    if tool_name == "investment.buy":
        return "请补充或核对理财产品名称和申购金额。"
    if tool_name in {"investment.redeem", "card.freeze", "card.unfreeze"}:
        return "请补充或核对要操作的产品或银行卡信息。"
    if tool_name == "transfer.split_create":
        return "请核对分账活动名称、总金额和参与人姓名后再继续。"
    if tool_name.startswith("subscription."):
        return "请补充或核对要操作的订阅名称。"
    return "操作信息不完整或格式不正确，请补充后再继续。"


def missing_requested_write_tools(
    request_text: str, task_progress: dict[str, Any]
) -> tuple[str, ...]:
    """Return explicit write intents not backed by successful server tool results."""
    request = request_text.casefold()
    if is_planning_only_request(request_text):
        return ()
    if _has_social_engineering_risk_signal(request):
        return ()
    history = task_progress.get("tools", [])
    succeeded = {
        item.get("tool_name")
        for item in history
        if isinstance(item, dict) and item.get("status") == "succeeded"
    }
    results = {
        item.get("tool_name"): item.get("result_data")
        for item in history
        if isinstance(item, dict)
        and item.get("status") == "succeeded"
        and isinstance(item.get("result_data"), dict)
    }
    required: list[str] = []
    has_amount = re.search(r"\d+(?:\.\d{1,2})?\s*(?:元|块|块钱)", request) is not None
    advisory_question = any(
        phrase in request for phrase in ("怎么", "怎样", "如何", "能否", "可以吗", "是否", "能不能")
    )

    if not advisory_question and any(
        phrase in request for phrase in ("可疑扣款", "重复扣费", "重复扣款")
    ):
        anomalies = results.get("bill.anomalies", {}).get("items", [])
        evidence = next(
            (
                item
                for item in anomalies
                if isinstance(item, dict)
                and "同一账户同一商户" in str(item.get("anomaly_reason", ""))
                and item.get("source_card_suffix")
            ),
            None,
        )
        if evidence is not None:
            if _requested_card_tool(request) == "card.freeze" and "card.freeze" not in succeeded:
                required.append("card.freeze")
            if "暂停" in request:
                subscriptions = results.get("subscription.list", {}).get("items", [])
                has_matching_subscription = any(
                    isinstance(item, dict)
                    and item.get("merchant") == evidence.get("merchant")
                    and item.get("status") == "active"
                    for item in subscriptions
                )
                if has_matching_subscription and "subscription.pause" not in succeeded:
                    required.append("subscription.pause")

    payday = not advisory_question and any(
        phrase in request for phrase in ("发薪", "工资", "薪资", "收入到账", "资金调度")
    )
    transfer_intent = has_explicit_transfer_write_intent(request_text)
    if payday and transfer_intent:
        transfer_tool = "transfer.schedule" if "定时" in request else "transfer.create"
        if transfer_tool not in succeeded:
            required.append(transfer_tool)
        if has_explicit_investment_write_intent(request_text):
            if "investment.buy" not in succeeded:
                required.append("investment.buy")

    if not advisory_question and transfer_intent:
        transfer_tool = "transfer.schedule" if "定时" in request else "transfer.create"
        if transfer_tool not in succeeded:
            required.append(transfer_tool)
    if not advisory_question and is_split_creation_request(request_text) and has_amount:
        split_tool = "transfer.split_collect" if "收取" in request else "transfer.split_create"
        if split_tool not in succeeded:
            required.append(split_tool)
    if not advisory_question and "取消" in request and "定时转账" in request:
        if "transfer.cancel_scheduled" not in succeeded:
            required.append("transfer.cancel_scheduled")
    if not advisory_question:
        card_tool = _requested_card_tool(request)
        if card_tool and card_tool not in succeeded:
            required.append(card_tool)

        subscription_tool = _requested_subscription_tool(request)
        if subscription_tool and subscription_tool not in succeeded:
            required.append(subscription_tool)
    if not advisory_question and has_explicit_investment_write_intent(request_text) and has_amount:
        if (
            "investment.buy" not in succeeded
            and unsuitable_requested_investment_message(request_text, task_progress) is None
        ):
            required.append("investment.buy")
    if (
        not advisory_question
        and has_explicit_investment_write_intent(request_text)
        and "赎回" in request
        and has_amount
        and "investment.redeem" not in succeeded
    ):
        required.append("investment.redeem")

    return tuple(dict.fromkeys(required))


def missing_write_input_message(
    request_text: str, task_progress: dict[str, Any], missing_tools: tuple[str, ...]
) -> str | None:
    """Prefer a specific user clarification when a requested write lacks its target."""
    request = request_text.casefold()
    if any(tool in missing_tools for tool in ("card.freeze", "card.unfreeze")) and not re.search(
        r"(?<!\d)\d{4}(?!\d)", request
    ):
        return "请提供要操作的银行卡尾号。"

    subscription_tools = {
        "subscription.pause",
        "subscription.resume",
        "subscription.cancel",
    }
    if subscription_tools.intersection(missing_tools):
        subscription_result = next(
            (
                item.get("result_data")
                for item in task_progress.get("tools", [])
                if isinstance(item, dict)
                and item.get("tool_name") == "subscription.list"
                and item.get("status") == "succeeded"
                and isinstance(item.get("result_data"), dict)
            ),
            None,
        )
        subscriptions = subscription_result.get("items", []) if subscription_result else []
        known_names = [
            item.get("merchant")
            for item in subscriptions
            if isinstance(item, dict) and isinstance(item.get("merchant"), str)
        ]
        if subscription_result is not None and not any(
            name.casefold() in request for name in known_names
        ):
            anomaly_result = next(
                (
                    item.get("result_data")
                    for item in task_progress.get("tools", [])
                    if isinstance(item, dict)
                    and item.get("tool_name") == "bill.anomalies"
                    and item.get("status") == "succeeded"
                    and isinstance(item.get("result_data"), dict)
                ),
                None,
            )
            evidence = next(
                (
                    item
                    for item in (anomaly_result or {}).get("items", [])
                    if isinstance(item, dict)
                    and item.get("source_card_suffix")
                    and "同一账户同一商户" in str(item.get("anomaly_reason", ""))
                ),
                None,
            )
            if (
                "subscription.pause" in missing_tools
                and evidence is not None
                and any(
                    isinstance(item, dict)
                    and item.get("merchant") == evidence.get("merchant")
                    and item.get("status") == "active"
                    for item in subscriptions
                )
            ):
                return None
            return "请说明要操作的订阅名称。"

    return None


def missing_payday_parameters_message(request_text: str) -> str | None:
    """Keep an explicit cross-scenario payday request open until its amounts are clear."""
    request = request_text.casefold()
    if not (
        any(phrase in request for phrase in ("发薪", "工资", "薪资", "收入到账", "资金调度"))
        and has_explicit_transfer_write_intent(request_text)
        and has_explicit_investment_write_intent(request_text)
    ):
        return None
    amount_count = len(re.findall(r"\d+(?:\.\d{1,2})?\s*(?:元|块钱|块)", request))
    has_reserve = any(phrase in request for phrase in ("预留", "保留", "留出", "留下"))
    explicitly_invest_remainder = bool(
        re.search(
            r"(?:剩余|余下|其余|余款|可用余额)[^，。；;]{0,12}(?:全部|都|全额|投资|理财|申购|买入|配置)"
            r"|(?:全部|都|全额)[^，。；;]{0,12}(?:剩余|余下|其余|余款|可用余额)",
            request,
        )
    )
    if amount_count >= 2 and has_reserve:
        return None
    if amount_count >= 1 and explicitly_invest_remainder and not has_reserve:
        return None
    return "请补充收款人、转账金额和希望保留的金额；如要投资全部余款，请明确说明。"


def requires_transfer_before_investment(request_text: str) -> bool:
    """Treat an explicit same-task transfer and investment as ordered writes."""
    request = request_text.casefold()
    if is_planning_only_request(request):
        return False
    transfer = has_explicit_transfer_write_intent(request_text)
    investment = has_explicit_investment_write_intent(request_text)
    return transfer and investment


def missing_explicit_write_parameters_message(request_text: str) -> str | None:
    """Clarify explicit, incomplete writes before the model can propose any side effect."""
    request = request_text.casefold()
    if is_planning_only_request(request):
        return None
    if "取消" in request and any(phrase in request for phrase in ("定时转账", "预约转账")):
        return None

    supplement = request_text.rsplit("\n\n用户补充：", 1)
    active_text = supplement[-1].casefold() if len(supplement) > 1 else request
    card_change = _requested_card_tool(request) is not None
    if card_change:
        suffix_source = active_text if len(supplement) > 1 else request
        suffix_source = re.sub(r"20\d{2}[-年]\d{1,2}(?:[-月]\d{1,2}(?:日)?)?", " ", suffix_source)
        suffix_source = re.sub(r"\d+(?:\.\d{1,2})?\s*(?:元|块钱|块)", " ", suffix_source)
        suffixes = set(re.findall(r"(?<!\d)\d{4}(?!\d)", suffix_source))
        if len(suffixes) != 1:
            if not suffixes:
                if any(
                    phrase in request
                    for phrase in ("刚才", "刚刚", "上一张", "上次操作", "之前操作")
                ):
                    return None
                if any(
                    phrase in request
                    for phrase in (
                        "关联",
                        "相关",
                        "对应",
                        "扣款卡",
                        "异常账单",
                        "重复扣费",
                        "可疑扣款",
                    )
                ):
                    return None
                return "请提供要操作的银行卡尾号。"
            return "请明确选择一张银行卡，并提供唯一的尾号。"

    transfer_intent = has_explicit_transfer_write_intent(request_text)
    investment_intent = has_explicit_investment_write_intent(request_text)
    if not transfer_intent and not investment_intent:
        split_creation = is_split_creation_request(request_text)
        if not split_creation:
            return None
        split_intent = parse_split_intent(request_text)
        missing_split_fields = []
        if split_intent.title is None:
            missing_split_fields.append("活动名称")
        if split_intent.amount_minor is None:
            missing_split_fields.append("总金额")
        if split_intent.participant_names is None:
            missing_split_fields.append("参与人姓名")
        if missing_split_fields:
            return "请补充分账" + "、".join(missing_split_fields) + "后再创建操作确认。"
        return None

    amount_count = len(re.findall(r"\d+(?:\.\d{1,2})?\s*(?:元|块钱|块)", request))
    has_amount = amount_count > 0
    recipient_pattern = (
        r"(?:转给|给)\s*(?!我\b|自己\b|用户\b)"
        r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9]{0,11}"
        r"(?=\s*(?:转|支付|汇款|打款|\d|[，,。！？；;]|$))"
    )
    payment_target_pattern = (
        r"(?:支付|汇款|打款)\s*(?:给\s*)?"
        r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9]{0,11}"
        r"(?=\s*\d)"
    )
    has_recipient = bool(
        re.search(recipient_pattern, request) or re.search(payment_target_pattern, request)
    )

    missing: list[str] = []
    if transfer_intent:
        if not has_recipient:
            missing.append("收款人")
        if not has_amount:
            missing.append("转账金额")

    payday_context = any(
        phrase in request for phrase in ("发薪", "工资", "薪资", "收入到账", "资金调度")
    )
    uses_remaining_budget = any(
        phrase in request for phrase in ("剩余", "余下", "其余", "可投金额", "可用余额")
    )
    if investment_intent:
        reserve_terms = any(phrase in request for phrase in ("预留", "保留", "留出", "留下"))
        explicit_remainder = uses_remaining_budget or (
            "赎回" in request and any(phrase in request for phrase in ("全部", "全额", "所有持仓"))
        )
        required_amount_count = 1
        if transfer_intent:
            required_amount_count = 2
            if reserve_terms and not uses_remaining_budget:
                required_amount_count = 3
            if payday_context and reserve_terms:
                required_amount_count = 2
        if not explicit_remainder and amount_count < required_amount_count:
            missing.append("申购金额或明确的剩余资金范围")

    if not missing:
        return None
    if transfer_intent and investment_intent:
        return "请补充" + "、".join(missing) + "；整组操作的信息明确后，才会创建第一项操作确认。"
    if len(missing) > 1:
        return "请补充" + "和".join(missing) + "后再继续。"
    return "请补充" + missing[0] + "后再继续。"


def split_proposal_mismatch_message(request_text: str, proposed: Any) -> str | None:
    """Reject split proposals whose material fields cannot be tied to explicit intent."""
    request = request_text.casefold()
    if not any(phrase in request for phrase in ("分账", "aa")):
        return "本次请求没有明确要求创建 AA 分账。"
    if not is_split_creation_request(request_text):
        if _has_query_cue(request):
            return "本次请求是查看分账信息，没有授权创建新的 AA 分账。"
        return "本次请求没有明确要求创建 AA 分账。"

    intent = parse_split_intent(request_text)
    if intent.title is None:
        return "请提供明确的分账活动名称，再创建确认请求。"
    if intent.amount_minor is None:
        return "请提供明确的分账总金额，再创建确认请求。"
    if intent.participant_names is None:
        return "请列出具体参与人姓名，再创建确认请求。"

    proposed_title = getattr(proposed, "title", None)
    proposed_amount = getattr(proposed, "amount_minor", None)
    proposed_participants = getattr(proposed, "participant_names", None)
    if proposed_title != intent.title:
        return "分账活动名称与您的描述不一致，未创建确认请求；请补充或核对名称。"
    if proposed_amount != intent.amount_minor:
        return "分账总金额与您的描述不一致，未创建确认请求；请补充或核对金额。"
    if tuple(proposed_participants or ()) != intent.participant_names:
        return "分账参与人与您的描述不一致，未创建确认请求；请补充或核对姓名。"
    return None


def unknown_requested_transfer_payee_message(
    request_text: str, task_progress: dict[str, Any]
) -> str | None:
    request = request_text.casefold()
    if any(
        phrase in request for phrase in ("怎么", "怎样", "如何", "能否", "可以吗", "是否", "能不能")
    ):
        return None
    if re.search(r"\d+(?:\.\d{1,2})?\s*(?:元|块|块钱)", request) is None:
        return None
    match = re.search(
        r"(?:转给\s*(?P<to_name>[\u4e00-\u9fffA-Za-z0-9]{1,12}?)\s*(?=\d|转|[，。！？；：,.!?;:\s]|$)|"
        r"给\s*(?P<from_name>[\u4e00-\u9fffA-Za-z0-9]{1,12}?)\s*转(?:账)?)",
        request,
    )
    if match is None:
        return None
    requested_name = match.group("to_name") or match.group("from_name")
    payee_result = next(
        (
            item.get("result_data")
            for item in task_progress.get("tools", [])
            if isinstance(item, dict)
            and item.get("tool_name") == "transfer.payees"
            and item.get("status") == "succeeded"
            and isinstance(item.get("result_data"), dict)
        ),
        None,
    )
    if payee_result is None:
        return None
    available = {
        item.get("display_name")
        for item in payee_result.get("items", [])
        if isinstance(item, dict) and isinstance(item.get("display_name"), str)
    }
    if requested_name in available:
        return None
    options = "、".join(sorted(available)) or "没有可用的已保存收款人"
    return f"没有找到名为“{requested_name}”的已保存收款人。请从现有收款人中选择：{options}。"


def unsuitable_requested_investment_message(
    request_text: str, task_progress: dict[str, Any]
) -> str | None:
    request = request_text.casefold()
    if any(
        phrase in request for phrase in ("怎么", "怎样", "如何", "能否", "可以吗", "是否", "能不能")
    ):
        return None
    if not any(phrase in request for phrase in ("申购", "买入", "购买")):
        return None
    if re.search(r"\d+(?:\.\d{1,2})?\s*(?:元|块|块钱)", request) is None:
        return None
    for item in task_progress.get("tools", []):
        if not isinstance(item, dict) or item.get("tool_name") != "investment.products":
            continue
        if item.get("status") != "succeeded" or not isinstance(item.get("result_data"), dict):
            continue
        for product in item["result_data"].get("items", []):
            if (
                isinstance(product, dict)
                and product.get("suitable") is False
                and isinstance(product.get("name"), str)
                and product["name"].casefold() in request
            ):
                return "该模拟产品超出当前用户风险等级范围，未创建申购。"
    return None
