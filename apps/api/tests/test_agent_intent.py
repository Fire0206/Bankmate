import pytest
from finorch_api.agent.intent import (
    has_explicit_transfer_write_intent,
    is_annual_bill_query,
    is_split_creation_request,
    is_subscription_reminder_query,
    parse_split_intent,
    requested_card_tool,
    requested_subscription_tool,
)


@pytest.mark.parametrize(
    ("prompt", "expected_title", "expected_amount", "expected_people"),
    [
        (
            "创建180元的火锅AA分账，和小林、小王平分",
            "火锅",
            18_000,
            ("小林", "小王"),
        ),
        (
            "帮我创建周末露营分账，总额253.50元，由林岚、陈舟参与",
            "周末露营",
            25_350,
            ("林岚", "陈舟"),
        ),
        (
            "请做一个电影票AA分账100元，参与者包括小李和小周",
            "电影票",
            10_000,
            ("小李", "小周"),
        ),
        (
            "创建分账，标题是团队聚餐，总额300元，参与人包括小林和小王",
            "团队聚餐",
            30_000,
            ("小林", "小王"),
        ),
        (
            "按原样使用活动名称“书友AA”创建120元AA分账，参与人是小林和小王",
            "书友AA",
            12_000,
            ("小林", "小王"),
        ),
    ],
)
def test_split_intent_extracts_variable_event_names_and_people(
    prompt: str, expected_title: str, expected_amount: int, expected_people: tuple[str, ...]
) -> None:
    intent = parse_split_intent(prompt)

    assert intent.title == expected_title
    assert intent.amount_minor == expected_amount
    assert intent.participant_names == expected_people


def test_split_intent_does_not_invent_missing_fields() -> None:
    intent = parse_split_intent("帮我创建AA分账，朋友们平分")

    assert intent.title is None
    assert intent.amount_minor is None
    assert intent.participant_names is None


def test_temporary_charge_pause_is_distinct_from_ambiguous_cancellation() -> None:
    assert (
        requested_subscription_tool("核对重复的音乐会员扣款后，暂时暂停扣费")
        == "subscription.pause"
    )
    assert requested_subscription_tool("取消这笔扣费") is None


def test_confirm_then_freeze_is_an_action_but_confirm_whether_frozen_is_a_query() -> None:
    assert requested_card_tool("核对依据，确认后冻结相关银行卡") == "card.freeze"
    assert requested_card_tool("确认这张银行卡是否已经冻结") is None


@pytest.mark.parametrize(
    "prompt",
    [
        "哪些自动续费快到期？提醒我下次扣款日期。",
        "帮我看一下订阅的续费时间。",
        "最近有没有即将扣费的会员？",
    ],
)
def test_subscription_timing_questions_are_distinct_from_inventory(prompt: str) -> None:
    assert is_subscription_reminder_query(prompt) is True


def test_subscription_inventory_and_write_requests_are_not_reminder_queries() -> None:
    assert is_subscription_reminder_query("我有哪些订阅？") is False
    assert is_subscription_reminder_query("暂停腾讯视频自动续费") is False


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("我的银行卡丢了，请帮我挂失尾号1042。", "card.report_lost"),
        ("麻烦把尾号1042的银行卡报失。", "card.report_lost"),
        ("我需要补办一张新的银行卡。", "card.replace"),
        ("请为尾号1042的挂失卡补发一张新卡。", "card.replace"),
        ("如何挂失银行卡？", None),
        ("查看银行卡的挂失状态。", None),
    ],
)
def test_card_loss_and_replacement_intents_are_explicit_and_distinct(
    prompt: str, expected: str | None
) -> None:
    assert requested_card_tool(prompt) == expected


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("在日常账户申请一张新的借记卡。", "card.apply"),
        ("尾号1042的卡已确认遗失，请给它补办新卡。", "card.replace"),
        ("把尾号1042这张卡的单笔支付上限改成4000元。", "card.controls"),
        ("请关闭1042卡的网上支付功能。", "card.controls"),
    ],
)
def test_card_application_replacement_and_control_phrases_are_distinct(
    prompt: str, expected: str
) -> None:
    assert requested_card_tool(prompt) == expected


def test_card_control_requests_are_not_misclassified_as_transfers() -> None:
    assert has_explicit_transfer_write_intent("请关闭1042卡的网上支付功能。") is False


@pytest.mark.parametrize(
    "prompt",
    [
        "给我一份2025年度收支账单。",
        "请总结2025年账目。",
        "查看去年全年消费和收入。",
    ],
)
def test_annual_bill_intent_accepts_year_and_summary_variants(prompt: str) -> None:
    assert is_annual_bill_query(prompt) is True


def test_annual_bill_intent_does_not_match_monthly_statement() -> None:
    assert is_annual_bill_query("统计本月收支账单。") is False


@pytest.mark.parametrize(
    ("prompt", "expected_title", "expected_amount", "expected_people"),
    [
        (
            "活动名是读书会聚餐，建立一笔315.60元AA分账，参与者为林岚、陈舟、王珂。",
            "读书会聚餐",
            31_560,
            ("林岚", "陈舟", "王珂"),
        ),
        (
            "请把周末羽毛球活动记作AA分账，合计178元，除我之外有陈舟和王珂参加。",
            "周末羽毛球活动",
            17_800,
            ("陈舟", "王珂"),
        ),
        (
            "创建读书会AA分账，每人出100元，参与者为林岚和陈舟。",
            "读书会",
            None,
            ("林岚", "陈舟"),
        ),
        (
            "创建AA分账，活动名为团队聚餐，总额300元\n\n用户补充：参与人包括小林和小王。",
            "团队聚餐",
            30_000,
            ("小林", "小王"),
        ),
    ],
)
def test_split_intent_handles_written_total_and_participant_forms(
    prompt: str,
    expected_title: str,
    expected_amount: int | None,
    expected_people: tuple[str, ...],
) -> None:
    intent = parse_split_intent(prompt)

    assert intent.title == expected_title
    assert intent.amount_minor == expected_amount
    assert intent.participant_names == expected_people


def test_split_creation_intent_does_not_turn_status_queries_into_writes() -> None:
    assert is_split_creation_request("查看AA分账状态。") is False
    assert is_split_creation_request("怎样创建AA分账？") is False
    assert is_split_creation_request("请把周末羽毛球活动记作AA分账。") is True
