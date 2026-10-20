from finorch_api.application.agent_workflow import (
    invalid_tool_input_name,
    missing_payday_parameters_message,
    missing_requested_write_tools,
    missing_write_input_message,
    tool_input_clarification_message,
    unknown_requested_transfer_payee_message,
    unsuitable_requested_investment_message,
)


def _history(*items: dict) -> dict:
    return {"tools": list(items)}


def _tool(name: str, *, result: dict | None = None) -> dict:
    return {"tool_name": name, "status": "succeeded", "result_data": result or {}}


def test_suspicious_charge_completion_requires_both_evidenced_writes() -> None:
    anomaly_result = {
        "items": [
            {
                "merchant": "腾讯视频会员",
                "source_card_suffix": "1042",
                "anomaly_reason": "同一账户同一商户在同一 UTC 日重复扣费提示",
            }
        ]
    }
    subscription_result = {"items": [{"merchant": "腾讯视频会员", "status": "active"}]}
    context = _history(
        _tool("bill.anomalies", result=anomaly_result),
        _tool("subscription.list", result=subscription_result),
        _tool("card.freeze"),
    )

    assert missing_requested_write_tools(
        "处置重复扣费，冻结关联银行卡并暂停对应订阅",
        context,
    ) == ("subscription.pause",)

    context["tools"].append(_tool("subscription.pause"))
    assert (
        missing_requested_write_tools(
            "处置重复扣费，冻结关联银行卡并暂停对应订阅",
            context,
        )
        == ()
    )


def test_payday_completion_requires_transfer_and_investment() -> None:
    context = _history(
        _tool("transfer.accounts"),
        _tool("bill.monthly_summary"),
        _tool("finance.payday_plan"),
        _tool("transfer.create"),
    )
    assert missing_requested_write_tools(
        "发薪日资金调度，给小林转 200 元，预留 3000 元，其余投资",
        context,
    ) == ("investment.buy",)

    context["tools"].append(_tool("investment.buy"))
    assert (
        missing_requested_write_tools(
            "发薪日资金调度，给小林转 200 元，预留 3000 元，其余投资",
            context,
        )
        == ()
    )


def test_payday_completion_detects_forward_amount_and_allocation_intents() -> None:
    assert missing_requested_write_tools(
        "本次发薪先转200元给小林，至少留下3500元；请先查询收支与余额，再按可投金额配置适合产品。",
        _history(),
    ) == ("transfer.create", "investment.buy")


def test_incomplete_payday_goal_stays_open_until_amounts_are_supplied() -> None:
    assert (
        missing_payday_parameters_message(
            "发薪日帮我规划资金，给小林转一部分，剩余买适合我的理财。"
        )
        == "请补充转账金额和希望保留在账户中的金额，再继续安排剩余资金。"
    )
    assert (
        missing_payday_parameters_message(
            "发薪日帮我规划资金，给小林转 200 元，账户预留 3000 元，其余买入理财。"
        )
        is None
    )
    assert missing_payday_parameters_message("发薪日理财怎么规划？") is None
    assert missing_payday_parameters_message("工资到账后给小林转 200 元，余下安排模拟理财。") == (
        "请补充转账金额和希望保留在账户中的金额，再继续安排剩余资金。"
    )


def test_invalid_required_tool_input_maps_to_a_user_clarification() -> None:
    progress = {
        "tools": [
            {
                "tool_name": "finance.payday_plan",
                "status": "failed",
                "error_code": "tool_input_invalid",
            }
        ]
    }

    tool_name = invalid_tool_input_name(progress)

    assert tool_name == "finance.payday_plan"
    assert tool_input_clarification_message(tool_name) == (
        "请补充或核对收款人、转账金额和账户预留金额。"
    )


def test_missing_card_target_becomes_a_clarification() -> None:
    assert (
        missing_write_input_message(
            "帮我把银行卡冻结一下",
            _history(_tool("card.list", result={"items": []})),
            ("card.freeze",),
        )
        == "请提供要操作的银行卡尾号。"
    )
    assert (
        missing_write_input_message(
            "冻结尾号1042的银行卡",
            _history(),
            ("card.freeze",),
        )
        is None
    )


def test_unknown_subscription_target_becomes_a_clarification() -> None:
    context = _history(_tool("subscription.list", result={"items": [{"merchant": "腾讯视频会员"}]}))
    assert (
        missing_write_input_message("取消我在某某平台的订阅", context, ("subscription.cancel",))
        == "请说明要操作的订阅名称。"
    )
    assert (
        missing_write_input_message("取消腾讯视频会员的自动续费", context, ("subscription.cancel",))
        is None
    )


def test_subscription_stop_intent_requires_cancel_while_pause_stays_reversible() -> None:
    assert missing_requested_write_tools("停止网易云音乐会员继续自动扣费", _history()) == (
        "subscription.cancel",
    )
    assert missing_requested_write_tools("暂停网易云音乐会员自动续费", _history()) == (
        "subscription.pause",
    )
    assert missing_requested_write_tools("关闭腾讯视频会员的自动续费", _history()) == (
        "subscription.cancel",
    )


def test_advisory_and_history_queries_do_not_require_writes() -> None:
    assert missing_requested_write_tools("怎样冻结我的银行卡？", _history()) == ()
    assert missing_requested_write_tools("查看 100 元转账记录", _history()) == ()


def test_social_engineering_risk_signals_do_not_force_write_intents() -> None:
    assert (
        missing_requested_write_tools(
            "网恋对象急用钱，让我给小林转8000元，不用再核实。", _history()
        )
        == ()
    )
    assert (
        missing_requested_write_tools(
            "我被催着给小林转200元，备注成退款，尽量别弹确认。", _history()
        )
        == ()
    )


def test_scheduled_transfer_intent_is_not_satisfied_by_balance_read() -> None:
    request = "在 2026-10-26 定时转给小林 50 元"
    assert missing_requested_write_tools(request, _history(_tool("transfer.accounts"))) == (
        "transfer.schedule",
    )
    assert missing_requested_write_tools(request, _history(_tool("transfer.schedule"))) == ()


def test_unknown_recipient_after_payee_lookup_returns_clarification() -> None:
    context = _history(_tool("transfer.payees", result={"items": [{"display_name": "小林"}]}))
    assert (
        unknown_requested_transfer_payee_message(
            "查看我的账户余额后，给张三转 100 元。",
            context,
        )
        == "没有找到名为“张三”的已保存收款人。请从现有收款人中选择：小林。"
    )
    assert (
        unknown_requested_transfer_payee_message(
            "给小林转账 100 元。",
            context,
        )
        is None
    )
    assert "张三" in unknown_requested_transfer_payee_message(
        "把 100 元转给张三；如果不是已保存的收款人，请先问我。",
        context,
    )


def test_server_product_risk_result_becomes_authoritative_rejection() -> None:
    context = _history(
        _tool(
            "investment.products",
            result={
                "items": [
                    {"name": "成长指数模拟", "suitable": False},
                    {"name": "安稳现金管理", "suitable": True},
                ]
            },
        )
    )
    assert (
        unsuitable_requested_investment_message(
            "申购 1000 元成长指数模拟。",
            context,
        )
        == "该模拟产品超出当前用户风险等级范围，未创建申购。"
    )
    assert (
        unsuitable_requested_investment_message(
            "申购 1000 元安稳现金管理。",
            context,
        )
        is None
    )
