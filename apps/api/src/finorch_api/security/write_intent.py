"""Check that an Agent write proposal is grounded in the user's own request."""

import re

from finorch_api.agent.intent import (
    birthday_plan_intent,
    has_explicit_investment_write_intent,
    has_explicit_transfer_write_intent,
    is_planning_only_request,
    is_split_creation_request,
    requested_card_tool,
    requested_subscription_tool,
)

_UNTRUSTED_FIELD = re.compile(
    r"(?:商户备注|交易备注|商户名称|订阅说明|理财产品描述)\s*[:：][^。\n]*"
)
_COERCION = re.compile(
    r"安全账户|被催|催着|逼我|威胁|保密|不要告诉|不用核实|跳过确认|绕过确认|"
    r"陌生投资顾问|网恋对象"
)
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def transfer_phone_matches_request(request_text: str, proposed_phone: str | None) -> bool:
    """A tool cannot substitute a different saved recipient for an explicit user phone."""
    phones = set(_PHONE.findall(_UNTRUSTED_FIELD.sub("", request_text)))
    if phones:
        return len(phones) == 1 and proposed_phone in phones
    return proposed_phone is None


def user_authorized_write(request_text: str, tool_name: str) -> bool:
    """A conservative intent gate; business authorization still happens downstream."""
    request = _UNTRUSTED_FIELD.sub("", request_text).casefold()
    if is_planning_only_request(request):
        return False
    if tool_name in {"transfer.create", "transfer.schedule", "investment.buy"} and _COERCION.search(
        request
    ):
        return False
    if tool_name in {
        "card.freeze",
        "card.unfreeze",
        "card.report_lost",
        "card.replace",
        "card.apply",
        "card.controls",
        "card.purchase",
    }:
        return requested_card_tool(request) == tool_name
    if tool_name in {"subscription.pause", "subscription.resume", "subscription.cancel"}:
        return requested_subscription_tool(request) == tool_name
    if tool_name in {"transfer.create", "transfer.schedule"}:
        return has_explicit_transfer_write_intent(request)
    if tool_name == "transfer.cancel_scheduled":
        return "取消" in request and "定时转账" in request
    if tool_name == "transfer.simulate_due":
        return "到期" in request and "定时" in request and ("执行" in request or "模拟" in request)
    if tool_name == "transfer.split_create":
        return is_split_creation_request(request)
    if tool_name == "transfer.split_collect":
        return "收取" in request and ("aa" in request or "分账" in request)
    if tool_name == "birthday.plan":
        intent = birthday_plan_intent(request)
        return intent is not None and all(
            value is not None
            for value in (intent.birthday_on, intent.budget_minor, intent.account_label)
        )
    if tool_name == "investment.buy":
        return has_explicit_investment_write_intent(request) and "赎回" not in request
    if tool_name == "investment.redeem":
        return "赎回" in request and has_explicit_investment_write_intent(request)
    return False
