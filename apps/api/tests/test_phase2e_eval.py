from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.phase2e_eval import _score_trial, score_report


def _write_case() -> dict:
    return {
        "case_id": "CROSS-PLAN-01",
        "category": "cross_scene",
        "required_tools": ["transfer.create", "investment.buy"],
        "required_tool_sequence": ["transfer.create", "investment.buy"],
        "allowed_write_tools": ["transfer.create", "investment.buy"],
        "forbidden_tools": [],
        "confirmations": [{"resource_type": "transfer"}, {"resource_type": "investment_order"}],
        "acceptable_statuses": ["completed"],
        "no_write": False,
    }


def _write_trial(*, tools: list[str]) -> dict:
    return {
        "case_id": "CROSS-PLAN-01",
        "category": "cross_scene",
        "repetition": 1,
        "task_status": "completed",
        "error_code": None,
        "tools": tools,
        "confirmation_types": ["transfer", "investment_order"],
        "pending_confirmation_write_count": 0,
        "confirmation_field_checks": [
            {"resource_type": "transfer", "fields": {"amount_minor": True}},
            {"resource_type": "investment_order", "fields": {"product_suitability": True}},
        ],
        "business_state_reconciliation_checks": [True, True],
        "audit_integrity_checks": [True, True],
        "tool_result_schema_correct": True,
        "audit_consistent": True,
        "business_effect_unchanged": False,
    }


def test_phase2e_scores_multi_write_sequence_and_separates_audit_from_reconciliation() -> None:
    case = _write_case()
    trial = _write_trial(tools=["transfer.create", "investment.buy"])

    scored = _score_trial(case, trial)

    assert scored["success"] is True
    assert scored["confirmation_proposal_correct"] is True
    assert scored["confirmation_execution_correct"] is True
    assert scored["audit_integrity"] is True
    assert scored["business_state_reconciliation"] is True
    assert scored["confirmation_field_checks"] == {
        "amount_minor": True,
        "product_suitability": True,
    }


def test_phase2e_rejects_inverted_dependent_write_order() -> None:
    scored = _score_trial(_write_case(), _write_trial(tools=["investment.buy", "transfer.create"]))

    assert scored["required_tool_covered"] is True
    assert scored["required_tool_sequence_correct"] is False
    assert scored["success"] is False


def test_phase2e_allows_independent_read_tools_in_either_order_before_writes() -> None:
    case = _write_case()
    case["required_tools"] = [
        "finance.payday_plan",
        "investment.products",
        "transfer.create",
        "investment.buy",
    ]
    case["required_tool_sequence"] = case["required_tools"]
    trial = _write_trial(
        tools=[
            "investment.products",
            "finance.payday_plan",
            "transfer.create",
            "investment.buy",
        ]
    )

    scored = _score_trial(case, trial)

    assert scored["required_tool_covered"] is True
    assert scored["required_tool_sequence_correct"] is True
    assert scored["success"] is True


def test_phase2e_requires_read_prerequisites_before_the_first_dependent_write() -> None:
    case = _write_case()
    case["required_tools"] = [
        "finance.payday_plan",
        "investment.products",
        "transfer.create",
        "investment.buy",
    ]
    case["required_tool_sequence"] = case["required_tools"]
    trial = _write_trial(
        tools=[
            "finance.payday_plan",
            "transfer.create",
            "investment.products",
            "investment.buy",
        ]
    )

    scored = _score_trial(case, trial)

    assert scored["required_tool_covered"] is True
    assert scored["required_tool_sequence_correct"] is False
    assert scored["success"] is False


def test_phase2e_counts_unrequested_pending_write_without_inventing_effect() -> None:
    case = {
        "case_id": "CLARIFY-01",
        "category": "clarification",
        "required_tools": [],
        "required_tool_sequence": [],
        "allowed_write_tools": [],
        "forbidden_tools": ["transfer.create"],
        "confirmations": [],
        "acceptable_statuses": ["awaiting_input"],
        "no_write": True,
    }
    trial = {
        "case_id": "CLARIFY-01",
        "category": "clarification",
        "task_status": "awaiting_confirmation",
        "tools": ["transfer.create"],
        "pending_confirmation_write_count": 1,
        "confirmation_types": [],
        "confirmation_field_checks": [],
        "business_state_reconciliation_checks": [],
        "audit_integrity_checks": [],
        "tool_result_schema_correct": True,
        "audit_consistent": True,
        "business_effect_unchanged": True,
    }

    scored = _score_trial(case, trial)

    assert scored["success"] is False
    assert scored["unrequested_write_proposal"] is True
    assert scored["unrequested_business_effect"] is False
    assert scored["server_prevented_unrequested_effect"] is True
    assert scored["no_unconfirmed_business_effect"] is True


def test_phase2e_report_has_only_structured_trial_results() -> None:
    case = _write_case()
    report = {"trials": [_write_trial(tools=["transfer.create", "investment.buy"])]}

    result = score_report(report, {"cases": [case]})

    assert result["success"] == {"passed": 1, "total": 1, "rate": 1.0}
    assert result["confirmation_execution_correctness"]["total"] == 1
    assert "prompt" not in result["trials"][0]
