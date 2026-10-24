"""Protect the independent Phase 3 feature holdout from accidental drift."""

import hashlib
import importlib.util
import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = REPOSITORY_ROOT / "apps" / "api" / "scripts" / "phase3-holdout-cases.json"
LOCK_PATH = REPOSITORY_ROOT / "apps" / "api" / "scripts" / "phase3-holdout.lock.json"
EVAL_SCRIPT_PATH = REPOSITORY_ROOT / "apps" / "api" / "scripts" / "deepseek_eval.py"
EVAL_MODULE_SPEC = importlib.util.spec_from_file_location("phase3_deepseek_eval", EVAL_SCRIPT_PATH)
if EVAL_MODULE_SPEC is None or EVAL_MODULE_SPEC.loader is None:
    raise RuntimeError("Cannot load the evaluation case catalog.")
EVAL_MODULE = importlib.util.module_from_spec(EVAL_MODULE_SPEC)
EVAL_MODULE_SPEC.loader.exec_module(EVAL_MODULE)
development_cases = EVAL_MODULE.cases


def test_phase3_holdout_is_frozen_unique_and_independent() -> None:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    cases = data["cases"]
    canonical = json.dumps(
        cases,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    case_ids = [case["id"] for case in cases]
    prompts = [case["prompt"] for case in cases]
    dev_prompts = {case.get("prompt") for case in development_cases()}

    assert data["dataset_version"] == lock["dataset_version"]
    assert hashlib.sha256(canonical).hexdigest() == lock["holdout_sha256"]
    assert case_ids == lock["case_ids"]
    assert len(case_ids) == lock["case_count"]
    assert len(set(case_ids)) == len(case_ids)
    assert len(set(prompts)) == len(prompts)
    assert not set(prompts) & dev_prompts
    assert lock["source_commit"]


def test_phase3_evaluator_selects_the_frozen_dataset(monkeypatch) -> None:
    monkeypatch.setenv("FINORCH_EVAL_DATASET", "phase3-holdout")
    monkeypatch.delenv("FINORCH_EVAL_CASES", raising=False)

    cases = EVAL_MODULE.selected_cases()

    assert len(cases) == 10
    assert all(case["phase3_holdout"] for case in cases)


def test_annual_report_holdout_compares_tool_result_to_api(monkeypatch) -> None:
    monthly_totals = [
        {"month": f"2026-{month:02d}", "income_minor": month, "expense_minor": month * 2}
        for month in range(1, 13)
    ]
    result = {
        "year": 2026,
        "currency": "CNY",
        "income_minor": 78,
        "expense_minor": 156,
        "net_minor": -78,
        "monthly_totals": monthly_totals,
        "categories": [{"category": "dining", "amount_minor": 156}],
    }
    monkeypatch.setattr(EVAL_MODULE, "call_api", lambda *_args: (200, result))

    checks = EVAL_MODULE.verify_phase3_holdout(
        {"verification": "annual_report"},
        None,
        {"steps": [{"tool_name": "bill.annual_report", "result_data": result}]},
    )

    assert all(checks.values())

    mismatched = result | {"net_minor": 0}
    monkeypatch.setattr(EVAL_MODULE, "call_api", lambda *_args: (200, mismatched))
    checks = EVAL_MODULE.verify_phase3_holdout(
        {"verification": "annual_report"},
        None,
        {"steps": [{"tool_name": "bill.annual_report", "result_data": result}]},
    )
    assert not checks["tool_result_matches_annual_api"]
