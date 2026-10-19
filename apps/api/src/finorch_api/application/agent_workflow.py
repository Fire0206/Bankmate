import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import AgentTask, TaskStep, ToolExecution


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
    if tool_name.startswith("subscription."):
        return "请补充或核对要操作的订阅名称。"
    return "操作信息不完整或格式不正确，请补充后再继续。"


def missing_requested_write_tools(
    request_text: str, task_progress: dict[str, Any]
) -> tuple[str, ...]:
    """Return explicit write intents not backed by successful server tool results."""
    request = request_text.casefold()
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
            if "冻结" in request and "card.freeze" not in succeeded:
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
    transfer_intent = has_amount and (
        re.search(r"转给\s*[\u4e00-\u9fffA-Za-z0-9]{1,12}", request) is not None
        or re.search(r"给[\u4e00-\u9fffA-Za-z0-9]{1,12}转(?:账)?", request) is not None
        or (
            "转账" in request
            and not any(phrase in request for phrase in ("记录", "历史", "查询", "查看"))
        )
    )
    if payday and transfer_intent:
        transfer_tool = "transfer.schedule" if "定时" in request else "transfer.create"
        if transfer_tool not in succeeded:
            required.append(transfer_tool)
        if any(phrase in request for phrase in ("理财", "投资", "申购", "买入")):
            if "investment.buy" not in succeeded:
                required.append("investment.buy")

    if not advisory_question and transfer_intent:
        transfer_tool = "transfer.schedule" if "定时" in request else "transfer.create"
        if transfer_tool not in succeeded:
            required.append(transfer_tool)
    if not advisory_question and "分账" in request and has_amount:
        split_tool = "transfer.split_collect" if "收取" in request else "transfer.split_create"
        if split_tool not in succeeded:
            required.append(split_tool)
    if not advisory_question and "取消" in request and "定时转账" in request:
        if "transfer.cancel_scheduled" not in succeeded:
            required.append("transfer.cancel_scheduled")
    if (
        not advisory_question
        and "冻结" in request
        and any(phrase in request for phrase in ("银行卡", "尾号", "卡 "))
    ):
        if "card.freeze" not in succeeded:
            required.append("card.freeze")
    if (
        not advisory_question
        and "解冻" in request
        and any(phrase in request for phrase in ("银行卡", "尾号", "卡 "))
    ):
        if "card.unfreeze" not in succeeded:
            required.append("card.unfreeze")
    if (
        not advisory_question
        and any(phrase in request for phrase in ("暂停", "取消"))
        and any(phrase in request for phrase in ("自动扣费", "自动续费", "订阅", "会员"))
    ):
        action = "subscription.pause" if "暂停" in request else "subscription.cancel"
        if action not in succeeded:
            required.append(action)
    if (
        not advisory_question
        and "恢复" in request
        and any(phrase in request for phrase in ("自动扣费", "自动续费", "订阅", "会员"))
    ):
        if "subscription.resume" not in succeeded:
            required.append("subscription.resume")
    if (
        not advisory_question
        and any(phrase in request for phrase in ("申购", "买入", "购买"))
        and has_amount
    ):
        if "investment.buy" not in succeeded:
            required.append("investment.buy")
    if (
        not advisory_question
        and "赎回" in request
        and has_amount
        and "investment.redeem" not in succeeded
    ):
        required.append("investment.redeem")

    return tuple(dict.fromkeys(required))


def missing_payday_parameters_message(request_text: str) -> str | None:
    """Keep an explicit cross-scenario payday request open until its amounts are clear."""
    request = request_text.casefold()
    if any(
        phrase in request for phrase in ("怎么", "怎样", "如何", "能否", "可以吗", "是否", "能不能")
    ):
        return None
    if not (
        any(phrase in request for phrase in ("发薪", "工资", "薪资", "收入到账", "资金调度"))
        and "转" in request
        and any(phrase in request for phrase in ("理财", "投资", "申购", "买入", "购买"))
    ):
        return None
    amounts = re.findall(r"\d+(?:\.\d{1,2})?\s*(?:元|块钱|块)", request)
    if len(amounts) >= 2:
        return None
    return "请补充转账金额和希望保留在账户中的金额，再继续安排剩余资金。"


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
