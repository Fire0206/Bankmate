from bankmate_api.agent.intent import has_explicit_investment_write_intent
from bankmate_api.application.agent_workflow import (
    _requested_card_tool,
    _requested_subscription_tool,
    invalid_tool_input_name,
    missing_explicit_write_parameters_message,
    missing_payday_parameters_message,
    missing_requested_write_tools,
    missing_required_read_tools,
    missing_write_input_message,
    requires_transfer_before_investment,
    split_proposal_mismatch_message,
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

    assert missing_requested_write_tools(
        "发薪日资金调度，给小林转 200 元，预留 3000 元，其余投资",
        _history(),
    ) == ("transfer.create", "investment.buy")


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
        == "请补充收款人、转账金额和希望保留的金额；如要投资全部余款，请明确说明。"
    )
    assert (
        missing_payday_parameters_message(
            "发薪日帮我规划资金，给小林转 200 元，账户预留 3000 元，其余买入理财。"
        )
        is None
    )
    assert missing_payday_parameters_message("发薪日理财怎么规划？") is None
    assert missing_payday_parameters_message("工资到账后给小林转 200 元，并安排模拟理财。") == (
        "请补充收款人、转账金额和希望保留的金额；如要投资全部余款，请明确说明。"
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


def test_explicit_payday_intents_accept_remainder_and_suitability_wording() -> None:
    assert has_explicit_investment_write_intent(
        "本次发薪先转200元给小林，至少留下3500元；请先查询收支与余额，再按可投金额配置适合产品。"
    )
    assert has_explicit_investment_write_intent("剩余买适合我的理财")
    assert has_explicit_investment_write_intent("剩余资金全部投入适合的理财产品")


def test_subscription_stop_with_continue_word_is_still_cancel() -> None:
    assert _requested_subscription_tool("停止网易云音乐会员继续自动扣费") == ("subscription.cancel")


def test_future_restore_language_does_not_request_an_immediate_resume() -> None:
    request = "临时暂停腾讯视频会员自动续费，之后可以恢复"
    assert missing_requested_write_tools(request, _history()) == ("subscription.pause",)
    assert (
        missing_requested_write_tools(
            request,
            _history(_tool("subscription.pause")),
        )
        == ()
    )
    assert missing_requested_write_tools("恢复腾讯视频会员的自动续费", _history()) == (
        "subscription.resume",
    )


def test_advisory_and_history_queries_do_not_require_writes() -> None:
    assert missing_requested_write_tools("怎样冻结我的银行卡？", _history()) == ()
    assert missing_requested_write_tools("查看 100 元转账记录", _history()) == ()
    assert missing_requested_write_tools("最近的转账和预约付款各是什么状态？", _history()) == ()
    assert missing_requested_write_tools("哪些模拟理财产品符合我的风险承受级别？", _history()) == ()
    assert missing_explicit_write_parameters_message("最近的转账和预约付款各是什么状态？") is None
    assert (
        missing_explicit_write_parameters_message("哪些模拟理财产品符合我的风险承受级别？") is None
    )


def test_card_direction_recognizes_action_scope_and_negation() -> None:
    assert _requested_card_tool("解除尾号4318储蓄卡的冻结状态。") == "card.unfreeze"
    assert _requested_card_tool("将被冻结的银行卡恢复使用。") == "card.unfreeze"
    assert _requested_card_tool("重新启用已冻结的银行卡。") == "card.unfreeze"
    assert _requested_card_tool("冻结尾号1042的银行卡。") == "card.freeze"
    assert _requested_card_tool("保持银行卡冻结，不要解冻。") is None
    assert _requested_card_tool("查看卡片冻结状态。") is None


def test_ambiguous_card_write_is_stopped_before_tool_execution() -> None:
    request = "我记不清要冻结的是1042还是4318，先帮我处理一下。"

    assert missing_explicit_write_parameters_message(request) == (
        "请明确选择一张银行卡，并提供唯一的尾号。"
    )


def test_subscription_direction_uses_current_action_not_state_description() -> None:
    assert (
        _requested_subscription_tool("把云盘会员从暂停状态恢复成正常续费。")
        == "subscription.resume"
    )
    assert _requested_subscription_tool("暂停云盘会员自动续费，之后可以恢复。") == (
        "subscription.pause"
    )
    assert _requested_subscription_tool("查看云盘会员当前是否暂停。") is None
    assert _requested_subscription_tool("取消之后查看云盘会员历史。") is None


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
    assert (
        unknown_requested_transfer_payee_message(
            "明天给小林定时转 50 元。",
            context,
        )
        is None
    )
    scheduled_unknown = unknown_requested_transfer_payee_message(
        "明天给邻居王定时转 50 元。",
        context,
    )
    assert scheduled_unknown is not None
    assert "邻居王" in scheduled_unknown
    assert "邻居王定时" not in scheduled_unknown
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
    assert (
        missing_requested_write_tools(
            "申购 1000 元成长指数模拟。",
            _history(
                _tool(
                    "investment.products",
                    result={"items": [{"name": "成长指数模拟", "suitable": False}]},
                )
            ),
        )
        == ()
    )


def test_incomplete_write_intents_pause_before_any_proposal() -> None:
    assert missing_explicit_write_parameters_message("我爱人生日想预留1000元买鲜花和蛋糕") == (
        "请补充生日日期，例如11月20日。"
    )
    assert missing_explicit_write_parameters_message("冻结银行卡尾号1042或4318") == (
        "请明确选择一张银行卡，并提供唯一的尾号。"
    )
    assert missing_explicit_write_parameters_message("给小林转一部分钱") == (
        "请补充转账金额后再继续。"
    )
    assert missing_explicit_write_parameters_message("给小林转200元，再买一只低风险理财") == (
        "请补充申购金额或明确的剩余资金范围；整组操作的信息明确后，才会创建第一项操作确认。"
    )
    assert (
        missing_explicit_write_parameters_message(
            "给小林转200元，再把剩余资金全部投入适合的理财产品"
        )
        is None
    )


def test_card_lock_synonyms_and_incomplete_split_are_clarified_preflight() -> None:
    assert missing_explicit_write_parameters_message("帮我锁上银行卡") == (
        "请提供要操作的银行卡尾号。"
    )
    assert missing_explicit_write_parameters_message("把尾号1042或4318的卡锁住") == (
        "请明确选择一张银行卡，并提供唯一的尾号。"
    )
    assert "参与人姓名" in missing_explicit_write_parameters_message(
        "创建一笔火锅AA分账，总金额180元"
    )
    assert (
        missing_explicit_write_parameters_message(
            "检查有没有重复的音乐会员扣款。若确定来自这张卡，就冻结卡并暂停扣费。"
        )
        is None
    )


def test_clarification_can_resolve_a_previously_ambiguous_card() -> None:
    assert (
        missing_explicit_write_parameters_message(
            "冻结银行卡尾号1042或4318\n\n用户补充：请冻结尾号1042"
        )
        is None
    )


def test_split_proposal_must_match_explicit_title_amount_and_participants() -> None:
    from types import SimpleNamespace

    request = "创建180元的火锅AA分账，和小林、小王平分"
    assert (
        split_proposal_mismatch_message(
            request,
            SimpleNamespace(title="火锅", amount_minor=18_000, participant_names=["小林", "小王"]),
        )
        is None
    )
    assert "名称" in split_proposal_mismatch_message(
        request,
        SimpleNamespace(
            title="火锅AA分账", amount_minor=18_000, participant_names=["小林", "小王"]
        ),
    )
    assert "参与人" in split_proposal_mismatch_message(
        request,
        SimpleNamespace(
            title="火锅", amount_minor=18_000, participant_names=["小林", "小王", "平分"]
        ),
    )


def test_transfer_and_investment_are_a_dependent_write_sequence() -> None:
    assert requires_transfer_before_investment("先给小林转200元，再申购安稳现金管理100元") is True
    assert requires_transfer_before_investment("如何安排转账和理财？") is False
    assert (
        requires_transfer_before_investment(
            "工资到账后给小林转200元，留5000元，剩余资金投资多少？请只计算方案，不执行。"
        )
        is False
    )
    assert (
        missing_explicit_write_parameters_message(
            "只计算给小林转账并预留资金后的理财额度，不执行。"
        )
        is None
    )


def test_split_creation_with_per_person_amount_requires_total() -> None:
    assert (
        missing_explicit_write_parameters_message(
            "创建读书会AA分账，每人出100元，参与者为林岚和陈舟。"
        )
        == "请补充分账总金额后再创建操作确认。"
    )


def test_renewal_reminders_are_required_and_combined_annual_reads_are_both_required() -> None:
    assert missing_required_read_tools("最近有哪些会员快要扣费？", _history()) == (
        "subscription.reminders",
    )
    assert missing_required_read_tools(
        "查看2025年度账单并告诉我订阅什么时候续费",
        _history(_tool("bill.annual_report")),
    ) == ("subscription.reminders",)
    assert missing_required_read_tools("我有哪些订阅？", _history()) == ()


def test_saved_birthday_budget_and_order_status_require_the_read_tool() -> None:
    request = "查看已保存的生日赠礼预算和订单状态。"

    assert missing_required_read_tools(request, _history()) == ("birthday.list",)
    assert missing_required_read_tools(request, _history(_tool("birthday.list"))) == ()
    assert missing_required_read_tools("安排生日鲜花和蛋糕，预留1000元。", _history()) == ()


def test_birthday_plan_with_month_day_requires_the_planning_tool() -> None:
    request = "为11月20日生日的朋友安排鲜花和蛋糕，日常账户预留2000元预算。"

    assert missing_requested_write_tools(request, _history()) == ("birthday.plan",)
