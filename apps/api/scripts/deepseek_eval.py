"""Run a small, live DeepSeek tool-calling evaluation against a local FinOrch API.

Only sanitized case labels, selected tool names, task states, and error codes are
printed. Raw prompts, API keys, and model responses are never written to output.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from finorch_api.config import Settings

BASE_URL = os.getenv("FINORCH_EVAL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def call_api(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    idempotency_key: str | None = None,
) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
            "Idempotency-Key": idempotency_key or str(uuid4()),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            payload = json.loads(response.read()) if response.status != 204 else {}
            return response.status, payload
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        return error.code, payload


def error_code(payload: dict) -> str | None:
    error = payload.get("error")
    return error.get("code") if isinstance(error, dict) else None


def tool_names(task: dict) -> list[str]:
    return [
        step["tool_name"]
        for step in task.get("steps", [])
        if isinstance(step.get("tool_name"), str)
    ]


def last_result(task: dict) -> dict:
    for step in reversed(task.get("steps", [])):
        data = step.get("result_data")
        if isinstance(data, dict):
            return data
    return {}


def task_error(task: dict) -> str | None:
    if task.get("error_code"):
        return task["error_code"]
    for step in reversed(task.get("steps", [])):
        if step.get("error_code"):
            return step["error_code"]
    return None


def request_case(case: dict) -> dict:
    conversation_id = str(uuid4())
    status, task = call_api(
        "POST",
        "/api/v1/agent/tasks",
        {"request_text": case["prompt"], "conversation_id": conversation_id},
    )
    if status >= 400 or not isinstance(task, dict) or "id" not in task:
        return {
            "id": case["id"],
            "name": case["name"],
            "selected_tools": [],
            "task_status": "request_failed",
            "error_code": error_code(task),
            "pass": False,
        }

    selected = tool_names(task)
    expected_tools = case.get("expected_tools", [])
    selected_ok = (
        any(name in selected for name in expected_tools) if expected_tools else not selected
    )
    task_ok = False
    parameters_ok = True
    parameter_checks: dict[str, bool] = {}
    confirmation = task.get("confirmation")
    confirmed_task = task

    if case.get("kind") == "clarify":
        task_ok = task.get("status") == "awaiting_input" and confirmation is None and not selected
    elif case.get("kind") == "reject":
        task_ok = confirmation is None
        if "investment.buy" in selected:
            task_ok = task_ok and task.get("status") == "failed"
            parameters_ok = task_error(task) == case.get("expected_error")
            parameter_checks["expected_error"] = parameters_ok
        else:
            results = [
                step.get("result_data")
                for step in task.get("steps", [])
                if isinstance(step.get("result_data"), dict)
            ]
            unsuitable = any(
                item.get("name") == case.get("unsuitable_product") and item.get("suitable") is False
                for result in results
                for item in result.get("items", [])
                if isinstance(item, dict)
            )
            parameter_checks["unsuitable_product"] = unsuitable
            task_ok = task_ok and task.get("status") == "completed" and unsuitable
    elif confirmation:
        checks = case.get("confirmation", {})
        parameter_checks["resource_type"] = confirmation.get("resource_type") == checks.get(
            "resource_type"
        )
        parameters_ok = parameter_checks["resource_type"]
        details = confirmation.get("details") or {}
        for key in ("amount_minor", "payee_name", "transfer_type", "target_status"):
            if key in checks:
                detail_key = (
                    "total_amount_minor"
                    if key == "amount_minor" and checks.get("resource_type") == "split"
                    else key
                )
                actual = (
                    details.get(detail_key) if key != "target_status" else confirmation.get(key)
                )
                parameter_checks[key] = actual == checks[key]
                parameters_ok = parameters_ok and parameter_checks[key]
        if "scheduled_at" in checks:
            actual_time = details.get("scheduled_at")
            parameter_checks["scheduled_at"] = isinstance(actual_time, str)
            if actual_time:
                parameter_checks["scheduled_at"] = (
                    parameter_checks["scheduled_at"] and actual_time[:10] == checks["scheduled_at"]
                )
            parameters_ok = parameters_ok and parameter_checks["scheduled_at"]
        if "resource_label" in checks:
            parameter_checks["resource_label"] = (
                confirmation.get("resource_label") == checks["resource_label"]
            )
            parameters_ok = parameters_ok and parameter_checks["resource_label"]
        if "participant_names" in checks:
            participants = details.get("participants", [])
            names = {item.get("display_name") for item in participants if isinstance(item, dict)}
            parameter_checks["participant_names"] = set(checks["participant_names"]).issubset(names)
            parameters_ok = parameters_ok and parameter_checks["participant_names"]
        if selected_ok and parameters_ok:
            confirm_status, confirmed_task = call_api(
                "POST",
                f"/api/v1/agent/tasks/{task['id']}/confirm",
                {
                    "challenge_id": confirmation["id"],
                    "parameters_hash": confirmation["parameters_hash"],
                },
                idempotency_key=confirmation["idempotency_key"],
            )
            task_ok = confirm_status < 400 and confirmed_task.get("status") == "completed"
            if task_ok and case.get("verify"):
                task_ok = verify_resource(case["verify"], confirmation)
        else:
            call_api("POST", f"/api/v1/agent/tasks/{task['id']}/cancel")
    else:
        task_ok = task.get("status") == "completed"
        if task_ok and expected_tools:
            parameters_ok = check_read_result(case, last_result(task))
            parameter_checks["read_result"] = parameters_ok

    return {
        "id": case["id"],
        "name": case["name"],
        "expected_tools": expected_tools,
        "selected_tools": selected,
        "task_status": confirmed_task.get("status", task.get("status")),
        "error_code": task_error(confirmed_task),
        "tool_selection_correct": selected_ok,
        "parameters_correct": parameters_ok,
        "parameter_checks": parameter_checks,
        "task_completed_or_clarified": task_ok,
        "pass": selected_ok and parameters_ok and task_ok,
    }


def check_read_result(case: dict, result: dict) -> bool:
    kind = case.get("result_kind")
    if kind == "items":
        return isinstance(result.get("items"), list)
    if kind == "money":
        return isinstance(result.get("expense_minor"), int) and isinstance(
            result.get("income_minor"), int
        )
    if kind == "portfolio":
        return isinstance(result.get("total_assets_minor"), int)
    if kind == "category":
        return bool(result.get("selected_category")) or isinstance(result.get("categories"), list)
    if kind == "cards":
        return bool(result.get("items"))
    return True


def verify_resource(verification: dict, confirmation: dict) -> bool:
    resource_id = confirmation.get("resource_id")
    if verification["type"] == "transfer":
        status, payload = call_api("GET", "/api/v1/transfers?limit=100")
        return status == 200 and any(
            item.get("id") == resource_id and item.get("status") == verification["status"]
            for item in payload.get("items", [])
        )
    if verification["type"] == "split":
        status, payload = call_api("GET", "/api/v1/splits?limit=100")
        return status == 200 and any(
            item.get("id") == resource_id and item.get("status") == verification["status"]
            for item in payload.get("items", [])
        )
    if verification["type"] == "investment":
        status, payload = call_api("GET", "/api/v1/investments/portfolio")
        return status == 200 and any(
            item.get("product_name") == confirmation.get("resource_label")
            for item in payload.get("holdings", [])
        )
    return False


def cases() -> list[dict]:
    scheduled_date = (datetime.now(UTC) + timedelta(days=7)).date().isoformat()
    return [
        {
            "id": 1,
            "name": "account_balances",
            "prompt": "查询我的账户余额",
            "expected_tools": ["transfer.accounts"],
            "result_kind": "items",
        },
        {
            "id": 2,
            "name": "saved_payees",
            "prompt": "我有哪些已保存的收款人",
            "expected_tools": ["transfer.payees"],
            "result_kind": "items",
        },
        {
            "id": 3,
            "name": "transfer_history",
            "prompt": "查看我的转账记录",
            "expected_tools": ["transfer.history"],
            "result_kind": "items",
        },
        {
            "id": 4,
            "name": "aa_split_history",
            "prompt": "查看我的 AA 分账记录",
            "expected_tools": ["transfer.splits"],
            "result_kind": "items",
        },
        {
            "id": 5,
            "name": "suitable_products",
            "prompt": "列出适合我风险等级的理财产品",
            "expected_tools": ["investment.products"],
            "result_kind": "items",
        },
        {
            "id": 6,
            "name": "compare_products",
            "prompt": "比较安稳现金管理和稳健短债组合",
            "expected_tools": ["investment.compare"],
            "result_kind": "items",
        },
        {
            "id": 7,
            "name": "portfolio",
            "prompt": "我的模拟理财持仓和总资产",
            "expected_tools": ["investment.portfolio"],
            "result_kind": "portfolio",
        },
        {
            "id": 8,
            "name": "investment_history",
            "prompt": "查看我的理财操作记录",
            "expected_tools": ["investment.orders"],
            "result_kind": "items",
        },
        {
            "id": 9,
            "name": "monthly_bill",
            "prompt": "我这个月的收入和支出各是多少",
            "expected_tools": ["bill.monthly_summary"],
            "result_kind": "money",
        },
        {
            "id": 10,
            "name": "food_spend",
            "prompt": "本月餐饮消费有多少",
            "expected_tools": ["bill.monthly_summary", "bill.transactions"],
            "result_kind": "category",
        },
        {
            "id": 11,
            "name": "anomaly_hints",
            "prompt": "最近有没有异常消费",
            "expected_tools": ["bill.anomalies"],
            "result_kind": "items",
        },
        {
            "id": 12,
            "name": "subscriptions",
            "prompt": "我有哪些自动扣费",
            "expected_tools": ["subscription.list"],
            "result_kind": "items",
        },
        {
            "id": 13,
            "name": "card_list",
            "prompt": "列出我的银行卡",
            "expected_tools": ["card.list"],
            "result_kind": "cards",
        },
        {
            "id": 14,
            "name": "card_status",
            "prompt": "查看尾号 1042 银行卡状态",
            "expected_tools": ["card.get"],
        },
        {
            "id": 15,
            "name": "confirmed_transfer",
            "prompt": "给小林转账 100 元",
            "expected_tools": ["transfer.create"],
            "confirmation": {
                "resource_type": "transfer",
                "amount_minor": 10000,
                "payee_name": "小林",
                "target_status": "executed",
            },
            "verify": {"type": "transfer", "status": "executed"},
        },
        {
            "id": 16,
            "name": "scheduled_transfer",
            "prompt": f"在 {scheduled_date} 10:00 定时转给小林 50 元",
            "expected_tools": ["transfer.schedule"],
            "confirmation": {
                "resource_type": "transfer",
                "amount_minor": 5000,
                "payee_name": "小林",
                "transfer_type": "scheduled",
                "scheduled_at": scheduled_date,
                "target_status": "scheduled",
            },
            "verify": {"type": "transfer", "status": "scheduled"},
        },
        {
            "id": 17,
            "name": "aa_split_create",
            "prompt": "帮我创建一笔 120 元火锅 AA 分账，和小林、小王一起平分",
            "expected_tools": ["transfer.split_create"],
            "confirmation": {
                "resource_type": "split",
                "amount_minor": 12000,
                "participant_names": ["小林", "小王"],
                "target_status": "open",
            },
            "verify": {"type": "split", "status": "open"},
        },
        {
            "id": 18,
            "name": "investment_purchase",
            "prompt": "申购 1000 元安稳现金管理",
            "expected_tools": ["investment.buy"],
            "confirmation": {
                "resource_type": "investment_order",
                "amount_minor": 100000,
                "resource_label": "安稳现金管理",
                "target_status": "executed",
            },
            "verify": {"type": "investment"},
        },
        {
            "id": 19,
            "name": "ambiguous_purchase",
            "prompt": "帮我申购一款理财",
            "expected_tools": [],
            "kind": "clarify",
        },
        {
            "id": 20,
            "name": "risk_mismatch",
            "prompt": "申购 1000 元成长指数模拟",
            "expected_tools": ["investment.buy", "investment.products"],
            "kind": "reject",
            "expected_error": "risk_mismatch",
            "unsuitable_product": "成长指数模拟",
        },
    ]


def selected_cases() -> list[dict]:
    all_cases = cases()
    requested = os.getenv("FINORCH_EVAL_CASES")
    if not requested:
        return all_cases
    by_name = {case["name"]: case for case in all_cases}
    selected_names = [name.strip() for name in requested.split(",") if name.strip()]
    if not selected_names or any(name not in by_name for name in selected_names):
        raise ValueError("FINORCH_EVAL_CASES contains an unknown or empty case selection")
    return [by_name[name] for name in selected_names]


def main() -> int:
    health_status, health = call_api("GET", "/api/v1/health")
    session_status, session = call_api("GET", "/api/v1/demo/session")
    if health_status != 200 or session_status != 200:
        print(json.dumps({"error": "local_api_unavailable"}))
        return 2
    if session.get("agent_provider") != "openai-compatible":
        print(json.dumps({"error": "openai_compatible_provider_not_active"}))
        return 2

    try:
        run_cases = selected_cases()
    except ValueError:
        print(json.dumps({"error": "invalid_case_selection"}))
        return 2
    results = [request_case(case) for case in run_cases]
    expected_tool_cases = [item for item in results if item["expected_tools"]]
    summary = {
        "model": Settings().llm_model or "configured by server",
        "case_count": len(results),
        "passed": sum(item["pass"] for item in results),
        "tool_selection_accuracy": ratio(
            sum(item["tool_selection_correct"] for item in expected_tool_cases),
            len(expected_tool_cases),
        ),
        "parameter_accuracy": ratio(
            sum(item["parameters_correct"] for item in results), len(results)
        ),
        "task_completion_accuracy": ratio(
            sum(item["task_completed_or_clarified"] for item in results), len(results)
        ),
        "cases": results,
    }
    report_path = Path(os.getenv("FINORCH_EVAL_REPORT", ".data/deepseek-eval-last.json"))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == len(results) else 1


def ratio(numerator: int, denominator: int) -> str:
    return f"{numerator / denominator:.0%}" if denominator else "n/a"


if __name__ == "__main__":
    sys.exit(main())
