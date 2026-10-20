import pytest
from finorch_api.agent.intent import parse_split_intent


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
