"""Deterministic scoring for the synthetic investment suitability questionnaire."""

from typing import TypedDict

QUESTIONNAIRE_VERSION = "demo-risk-v1"


class RiskAnswers(TypedDict):
    time_horizon: int
    loss_tolerance: int
    liquidity_capacity: int
    investment_experience: int


QUESTIONS = (
    {
        "key": "time_horizon",
        "title": "预计多久后需要使用这笔资金？",
        "options": ("随时", "半年内", "一至两年", "三至五年", "五年以上"),
    },
    {
        "key": "loss_tolerance",
        "title": "短期亏损时，你最多能接受多少？",
        "options": ("不能接受亏损", "约 5%", "约 10%", "约 20%", "超过 20%"),
    },
    {
        "key": "liquidity_capacity",
        "title": "除这笔投资外，你的备用资金情况如何？",
        "options": ("没有备用资金", "不足一个月", "一至三个月", "三至六个月", "六个月以上"),
    },
    {
        "key": "investment_experience",
        "title": "你接触有波动的投资产品多久了？",
        "options": ("从未接触", "不足一年", "一至三年", "三至五年", "五年以上"),
    },
)


def score_risk(answers: RiskAnswers) -> tuple[int, int]:
    values = tuple(answers[key] for key in RiskAnswers.__annotations__)
    if len(values) != 4 or any(type(value) is not int or not 1 <= value <= 5 for value in values):
        raise ValueError("Every risk answer must be an integer between 1 and 5.")
    score = sum(values)
    average_level = (score + 2) // 4
    # A high investment horizon cannot override weak loss tolerance or no emergency reserve.
    level = min(average_level, answers["loss_tolerance"], answers["liquidity_capacity"])
    return score, level
