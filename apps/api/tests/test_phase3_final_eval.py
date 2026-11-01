from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import phase2e_eval
from scripts.phase3_final_eval import DEV_CASES, HOLDOUT_CASES, _sanitized_report


def test_phase3_final_suites_are_independent_and_cover_requested_modules() -> None:
    dev = phase2e_eval._load_suite(DEV_CASES)
    holdout = phase2e_eval._load_suite(HOLDOUT_CASES)

    assert dev["split"] == "phase3-final-dev"
    assert holdout["split"] == "phase3-final-holdout"
    assert 30 <= len(dev["cases"]) <= 50
    assert 20 <= len(holdout["cases"]) <= 30
    assert {case["prompt"] for case in dev["cases"]}.isdisjoint(
        {case["prompt"] for case in holdout["cases"]}
    )
    assert {
        "cards",
        "bills",
        "subscriptions",
        "investments",
        "transfers",
        "birthday",
        "cross_scene",
        "scam_coercion",
    }.issubset({case["category"] for case in holdout["cases"]})
    assert all(
        set(case["allowed_write_tools"]).issubset(set(phase2e_eval.harness.WRITE_TOOLS))
        for case in dev["cases"] + holdout["cases"]
    )
    risk_case = next(case for case in dev["cases"] if case["case_id"] == "P3D-026")
    assert risk_case["required_tools"] == ["investment.products"]
    assert risk_case["allowed_write_tools"] == ["investment.buy"]
    for suite in (dev, holdout):
        otp_cases = [
            case
            for case in suite["cases"]
            if any(
                confirmation.get("confirmation_method") == "demo_otp"
                for confirmation in case["confirmations"]
            )
        ]
        assert len(otp_cases) == 1
        assert otp_cases[0]["confirmations"][0]["risk_level"] == "red"


def test_sanitized_phase3_report_excludes_prompts_and_provider_content() -> None:
    suite = phase2e_eval._load_suite(DEV_CASES)
    report = {
        "created_at_utc": "2026-10-25T00:00:00+00:00",
        "commit": "abc123",
        "model": "deepseek-flash",
        "complete": True,
        "metrics": {
            "success": {"passed": 1, "total": 1, "rate": 1.0},
            "trials": [
                {
                    "case_id": "P3D-001",
                    "success": True,
                    "tools": ["card.list"],
                    "raw_prompt": "must not be retained",
                    "provider_response": "must not be retained",
                }
            ],
        },
        "budget": {
            "cost_estimate": {"estimated_peak_cost_cny": 0.1, "provider_requests_started": 1},
            "phase2e_cumulative_cost_cny": 0.4,
        },
    }

    sanitized = _sanitized_report(report, suite)

    assert sanitized["prompts_included"] is False
    assert sanitized["provider_responses_included"] is False
    assert "must not be retained" not in str(sanitized)
    assert sanitized["budget"]["cumulative_cost_cny"] == 0.4
