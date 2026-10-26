"""Run the final BankMate model suites in the isolated Phase 2D harness.

Detailed reports stay under the ignored .data/ directory. A deliberately small
sanitized summary may be written under apps/api/evaluation-reports; it contains
case IDs, tool names, statuses, booleans, metrics, and cost estimates only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = API_ROOT.parents[1]
sys.path.insert(0, str(API_ROOT))

from scripts import phase2e_eval as evaluator  # noqa: E402

DATA_ROOT = REPOSITORY_ROOT / ".data"
DEV_CASES = API_ROOT / "scripts" / "phase3-final-dev-cases.json"
HOLDOUT_CASES = API_ROOT / "scripts" / "phase3-final-holdout-cases.json"
REPORT_ROOT = API_ROOT / "evaluation-reports"
HOLDOUT_LOCK = DATA_ROOT / "phase3-final-holdout-lock.json"
BUDGET_STATE = DATA_ROOT / "phase3-final-budget-state.json"
SOFT_BUDGET_CNY = 40.0
HARD_BUDGET_CNY = 100.0


def _configure() -> None:
    evaluator.HOLDOUT_LOCK = HOLDOUT_LOCK
    evaluator.BUDGET_STATE = BUDGET_STATE
    evaluator.SOFT_BUDGET_CNY = SOFT_BUDGET_CNY
    evaluator.HARD_BUDGET_CNY = HARD_BUDGET_CNY
    evaluator.BUDGET_SCOPE = "BankMate Phase 3 Final; previous phase spend excluded"


def _suite_path(split: str, requested: Path | None) -> Path:
    if requested is not None:
        return requested.resolve()
    return HOLDOUT_CASES if split == "phase3-final-holdout" else DEV_CASES


def _sanitized_report(report: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any]:
    metrics = report.get("metrics", {})
    allowed_trial_fields = (
        "case_id",
        "category",
        "repetition",
        "success",
        "task_status",
        "error_code",
        "tools",
        "required_tool_covered",
        "tool_path_correct",
        "unnecessary_write_tool",
        "required_tool_sequence_correct",
        "strict_tool_sequence_correct",
        "confirmation_proposal_correct",
        "confirmation_execution_correct",
        "strong_verification_correct",
        "confirmation_field_checks",
        "audit_integrity",
        "business_state_reconciliation",
        "no_unconfirmed_business_effect",
        "unrequested_write_proposal",
        "unrequested_business_effect",
        "server_prevented_unrequested_effect",
        "duplicate_write_tools",
        "provider_requests_for_trial",
    )
    trials = [
        {key: item.get(key) for key in allowed_trial_fields if key in item}
        for item in metrics.get("trials", [])
        if isinstance(item, dict)
    ]
    return {
        "report_schema_version": 1,
        "dataset_version": suite.get("suite_version"),
        "split": suite["split"],
        "created_at_utc": report.get("created_at_utc"),
        "source_commit": report.get("commit"),
        "model": report.get("model"),
        "case_count": len(suite["cases"]),
        "suite_sha256": evaluator._sha256(suite["cases"]),
        "complete": report.get("complete"),
        "stop_reason": report.get("stop_reason"),
        "budget": {
            "soft_ceiling_cny": SOFT_BUDGET_CNY,
            "hard_ceiling_cny": HARD_BUDGET_CNY,
            "estimated_peak_cost_cny": report.get("budget", {})
            .get("cost_estimate", {})
            .get("estimated_peak_cost_cny"),
            "cumulative_cost_cny": report.get("budget", {}).get(
                "cumulative_cost_cny",
                report.get("budget", {}).get("phase2e_cumulative_cost_cny"),
            ),
            "provider_requests_started": report.get("budget", {})
            .get("cost_estimate", {})
            .get("provider_requests_started"),
            "unaccounted_provider_requests": report.get("budget", {})
            .get("cost_estimate", {})
            .get("unaccounted_provider_requests"),
        },
        "metrics": {key: value for key, value in metrics.items() if key != "trials"},
        "trials": trials,
        "prompts_included": False,
        "provider_responses_included": False,
        "task_ids_included": False,
        "verification_codes_included": False,
        "secrets_included": False,
    }


def run(
    *,
    split: str,
    cases_path: Path | None,
    runs: int,
    report_path: Path | None,
    case_ids: list[str] | None = None,
) -> dict[str, Any]:
    _configure()
    path = _suite_path(split, cases_path)
    suite = evaluator._load_suite(path)
    if suite["split"] != split:
        raise ValueError("The suite split does not match --split.")
    required_count = (30, 50) if split == "phase3-final-dev" else (20, 30)
    if not required_count[0] <= len(suite["cases"]) <= required_count[1]:
        raise ValueError(f"{split} must contain {required_count[0]} to {required_count[1]} cases.")
    if case_ids:
        if split.endswith("holdout"):
            raise ValueError("Case selection is disabled for the frozen holdout.")
        by_id = {case["case_id"]: case for case in suite["cases"]}
        if not set(case_ids).issubset(by_id):
            raise ValueError("The selected case IDs are absent from the development suite.")
        suite = {**suite, "cases": [by_id[case_id] for case_id in case_ids]}
    if runs < 1 or runs > 3:
        raise ValueError("Use one to three repetitions per case.")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    detailed_path = report_path or (
        DATA_ROOT / f"phase3-final-{split}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    report = evaluator.run_suite(suite, runs=runs, report_path=detailed_path)
    sanitized = _sanitized_report(report, suite)
    public_path = REPORT_ROOT / f"{split}-{datetime.now(UTC).strftime('%Y-%m-%d')}.json"
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report["sanitized_report_path"] = str(public_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="BankMate Phase 3 Final DeepSeek evaluation.")
    parser.add_argument(
        "--split", choices=("phase3-final-dev", "phase3-final-holdout"), required=True
    )
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--case-ids", nargs="*")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--freeze-holdout", action="store_true")
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    _configure()
    try:
        path = _suite_path(args.split, args.cases)
        suite = evaluator._load_suite(path)
        if args.preflight:
            from scripts import phase2d_eval as harness

            print(json.dumps(harness.preflight_isolation(), ensure_ascii=False))
            return 0
        if args.freeze_holdout:
            lock = evaluator.freeze_holdout(suite)
            print(
                json.dumps(
                    {
                        "frozen": True,
                        "case_count": lock["case_count"],
                        "source_commit": lock["source_commit"],
                        "suite_sha256": lock["suite_sha256"],
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        if args.dry_run:
            from scripts import phase2d_eval as harness

            settings = harness._load_user_settings()
            print(
                json.dumps(
                    {
                        "split": suite["split"],
                        "unique_cases": len(suite["cases"]),
                        "target_trials": len(suite["cases"]) * args.runs,
                        "model": settings.llm_model,
                        "provider_key_configured": bool(settings.llm_api_key),
                        "soft_budget_cny": SOFT_BUDGET_CNY,
                        "hard_budget_cny": HARD_BUDGET_CNY,
                        "dry_run": True,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        report = run(
            split=args.split,
            cases_path=args.cases,
            runs=args.runs,
            report_path=args.report,
            case_ids=args.case_ids,
        )
        print(
            json.dumps(
                {
                    "split": args.split,
                    "complete": report.get("complete"),
                    "completed_trials": report.get("completed_trials"),
                    "target_trials": report.get("target_trials"),
                    "stop_reason": report.get("stop_reason"),
                    "estimated_peak_cost_cny": report.get("budget", {})
                    .get("cost_estimate", {})
                    .get("estimated_peak_cost_cny"),
                    "sanitized_report_path": report.get("sanitized_report_path"),
                },
                ensure_ascii=False,
            )
        )
        return 0 if report.get("complete") else 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"evaluation refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
