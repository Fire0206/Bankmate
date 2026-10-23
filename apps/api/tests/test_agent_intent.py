import pytest
from finorch_api.agent.intent import (
    is_split_creation_request,
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
