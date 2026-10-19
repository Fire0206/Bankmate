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

from sqlalchemy import select

from finorch_api.config import Settings
from finorch_api.infrastructure.database import get_session_factory
from finorch_api.infrastructure.models import Subscription
from finorch_api.reset import reset_demo_data, validate_reset_target

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
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {"error": {"code": "local_api_unavailable"}}


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
    if task.get("status") in {"awaiting_confirmation", "awaiting_input", "completed", "cancelled"}:
        return None
    for step in reversed(task.get("steps", [])):
        if step.get("error_code"):
            return step["error_code"]
    return None


def _reset_eval_database() -> None:
    """Reset only an explicitly opted-in, validated temporary test database."""
    settings = Settings()
    if os.getenv("FINORCH_EVAL_RESET_SYNTHETIC") != "1" or settings.environment != "test":
        raise RuntimeError("Phase 1E live evaluation requires an opted-in test database.")
    repository_root = Path(__file__).resolve().parents[3]
    validate_reset_target(
        environment=settings.environment,
        database_url=settings.database_url,
        repository_root=repository_root,
    )
    factory = get_session_factory(settings.database_url)
    with factory.begin() as session:
        reset_demo_data(session)


def _bump_subscription_version(merchant: str) -> None:
    """Create a deterministic stale-confirmation conflict in the test database."""
    settings = Settings()
    if settings.environment != "test":
        raise RuntimeError("Stale-confirmation injection is allowed only in test mode.")
    factory = get_session_factory(settings.database_url)
    with factory.begin() as session:
        subscription = session.scalar(select(Subscription).where(Subscription.merchant == merchant))
        if subscription is None:
            raise RuntimeError("The synthetic subscription fixture is missing.")
        subscription.version += 1


def _ordered_subsequence(actual: list[str], expected: list[str]) -> bool:
    cursor = 0
    for name in actual:
        if cursor < len(expected) and name == expected[cursor]:
            cursor += 1
    return cursor == len(expected)


def _tool_sequence_matches(case: dict, actual: list[str]) -> bool:
    expected = case.get("expected_tool_sequence", [])
    if set(case.get("forbidden_tools", [])) & set(actual):
        return False
    if case["name"].startswith("cross_payday_"):
        if not set(expected).issubset(actual):
            return False
        account_reads = [index for index, name in enumerate(actual) if name == "transfer.accounts"]
        bill_index = actual.index("bill.monthly_summary")
        plan_index = actual.index("finance.payday_plan")
        transfer_index = actual.index("transfer.create")
        products_index = actual.index("investment.products")
        investment_index = actual.index("investment.buy")
        portfolio_index = max(
            index for index, name in enumerate(actual) if name == "investment.portfolio"
        )
        return (
            len(account_reads) >= 2
            and account_reads[0] < plan_index
            and bill_index < plan_index < transfer_index
            and transfer_index < investment_index
            and products_index < investment_index
            and investment_index < account_reads[-1] < portfolio_index
        )
    return _ordered_subsequence(actual, expected)


def _verify_cross_state(case: dict, task: dict) -> dict[str, bool]:
    verification = case.get("verification")
    if verification == "suspicious_paused":
        _, cards = call_api("GET", "/api/v1/cards")
        _, subscriptions = call_api("GET", "/api/v1/subscriptions")
        card_ok = any(
            item.get("card_suffix") == "1042" and item.get("status") == "frozen"
            for item in cards.get("items", [])
        )
        subscription_ok = any(
            item.get("merchant") == "腾讯视频会员" and item.get("status") == "paused"
            for item in subscriptions.get("items", [])
        )
        return {"card_frozen": card_ok, "subscription_paused": subscription_ok}
    if verification == "suspicious_card_only":
        _, cards = call_api("GET", "/api/v1/cards")
        _, subscriptions = call_api("GET", "/api/v1/subscriptions")
        card_ok = any(
            item.get("card_suffix") == "1042" and item.get("status") == "frozen"
            for item in cards.get("items", [])
        )
        subscription_ok = any(
            item.get("merchant") == "腾讯视频会员" and item.get("status") == "active"
            for item in subscriptions.get("items", [])
        )
        return {"card_frozen": card_ok, "subscription_still_active": subscription_ok}
    if verification == "payday_complete":
        plan = next(
            (
                step.get("result_data")
                for step in reversed(task.get("steps", []))
                if step.get("tool_name") == "finance.payday_plan"
                and isinstance(step.get("result_data"), dict)
            ),
            {},
        )
        _, accounts = call_api("GET", "/api/v1/accounts")
        _, transfers = call_api("GET", "/api/v1/transfers?limit=100")
        _, portfolio = call_api("GET", "/api/v1/investments/portfolio")
        source = next(
            (
                item
                for item in accounts.get("items", [])
                if item.get("id") == "10000000-0000-4000-8000-000000000001"
            ),
            {},
        )
        transfer_ok = any(
            item.get("amount_minor") == 20_000
            and item.get("status") == "executed"
            and item.get("payee_name") == "小林"
            for item in transfers.get("items", [])
        )
        investment_ok = (
            isinstance(plan.get("investment_budget_minor"), int)
            and portfolio.get("invested_value_minor") == plan["investment_budget_minor"]
        )
        balance_ok = (
            isinstance(plan.get("reserve_amount_minor"), int)
            and source.get("balance_minor") == plan["reserve_amount_minor"]
        )
        return {
            "transfer_executed": transfer_ok,
            "investment_recorded": investment_ok,
            "reserved_balance_matches_plan": balance_ok,
        }
    if verification == "no_business_change":
        _, cards = call_api("GET", "/api/v1/cards")
        _, accounts = call_api("GET", "/api/v1/accounts")
        card_ok = any(
            item.get("card_suffix") == "1042" and item.get("status") == "active"
            for item in cards.get("items", [])
        )
        balance_ok = any(
            item.get("id") == "10000000-0000-4000-8000-000000000001"
            and item.get("balance_minor") == 1_250_000
            for item in accounts.get("items", [])
        )
        return {"card_unchanged": card_ok, "balance_unchanged": balance_ok}
    if verification == "anomaly_subscription_read":
        tool_results = {
            step.get("tool_name"): step.get("result_data")
            for step in task.get("steps", [])
            if isinstance(step.get("result_data"), dict)
        }
        anomalies = tool_results.get("bill.anomalies", {}).get("items", [])
        subscriptions = tool_results.get("subscription.list", {}).get("items", [])
        return {
            "duplicate_rule_found": any(
                "重复扣费提示" in str(item.get("anomaly_reason", ""))
                for item in anomalies
                if isinstance(item, dict)
            ),
            "subscription_data_returned": any(
                item.get("merchant") == "腾讯视频会员"
                for item in subscriptions
                if isinstance(item, dict)
            ),
        }
    if verification == "failed_target":
        return {
            "task_failed": task.get("status") == "failed",
            "expected_error": task_error(task) == case.get("expected_error"),
            "confirmation_not_created": task.get("confirmation") is None,
        }
    if verification == "risk_rejected":
        _, accounts = call_api("GET", "/api/v1/accounts")
        _, portfolio = call_api("GET", "/api/v1/investments/portfolio")
        _, orders = call_api("GET", "/api/v1/investments/orders")
        source = next(
            (
                item
                for item in accounts.get("items", [])
                if item.get("id") == "10000000-0000-4000-8000-000000000001"
            ),
            {},
        )
        return {
            "task_failed": task.get("status") == "failed",
            "expected_error": task_error(task) == case.get("expected_error"),
            "confirmation_not_created": task.get("confirmation") is None,
            "balance_unchanged": source.get("balance_minor") == 1_250_000,
            "holdings_unchanged": portfolio.get("holdings") == [],
            "orders_unchanged": orders.get("items") == [],
        }
    return {}


def _confirm_until_done(task: dict, case: dict) -> tuple[dict, list[str], str | None]:
    confirmed_types: list[str] = []
    expected_count = case.get("confirmations", 0)
    stale_error: str | None = None
    while task.get("status") == "awaiting_confirmation" and len(confirmed_types) < expected_count:
        challenge = task.get("confirmation") or {}
        confirmed_types.append(str(challenge.get("resource_type", "")))
        if case.get("stale_confirmation") and len(confirmed_types) == 2:
            _bump_subscription_version("腾讯视频会员")
        status, response = call_api(
            "POST",
            f"/api/v1/agent/tasks/{task['id']}/confirm",
            {
                "challenge_id": challenge.get("id"),
                "parameters_hash": challenge.get("parameters_hash"),
            },
            idempotency_key=challenge.get("idempotency_key"),
        )
        if status < 400:
            task = response
            continue
        stale_error = error_code(response)
        if not case.get("stale_confirmation"):
            return task, confirmed_types, stale_error
        _, task = call_api("GET", f"/api/v1/agent/tasks/{task['id']}")
        break
    return task, confirmed_types, stale_error


def request_cross_case(case: dict, task: dict) -> dict:
    initial_clarification = None
    if case.get("kind") == "clarify_then_execute":
        safe_read_tools = {"transfer.accounts", "bill.monthly_summary", "transfer.payees"}
        initial_tools = tool_names(task)
        initially_clarified = task.get("status") == "awaiting_input" and all(
            tool_name in safe_read_tools for tool_name in initial_tools
        )
        initial_clarification = initially_clarified
        if not initially_clarified:
            return {
                "id": case["id"],
                "name": case["name"],
                "task_status": task.get("status"),
                "selected_tools": tool_names(task),
                "tool_sequence_correct": False,
                "confirmation_count": 0,
                "pass": False,
            }
        status, task = call_api(
            "POST",
            f"/api/v1/agent/tasks/{task['id']}/input",
            {"request_text": case["followup"]},
        )
        if status >= 400:
            return {
                "id": case["id"],
                "name": case["name"],
                "task_status": "followup_failed",
                "selected_tools": tool_names(task),
                "tool_sequence_correct": False,
                "confirmation_count": 0,
                "pass": False,
            }

    if case.get("kind") == "cancel_after_first_confirmation":
        if task.get("status") != "awaiting_confirmation":
            return {
                "id": case["id"],
                "name": case["name"],
                "task_status": task.get("status"),
                "selected_tools": tool_names(task),
                "tool_sequence_correct": False,
                "confirmation_count": 0,
                "pass": False,
            }
        first, first_types, error = _confirm_until_done(
            task, case | {"confirmations": 1, "stale_confirmation": False}
        )
        if error or first.get("status") != "awaiting_confirmation":
            task = first
        else:
            cancel_status, cancelled = call_api("POST", f"/api/v1/agent/tasks/{task['id']}/cancel")
            task = cancelled if cancel_status < 400 else first
        checks = _verify_cross_state(case, task)
        sequence_ok = _tool_sequence_matches(case, tool_names(task))
        passed = (
            task.get("status") == "cancelled"
            and first_types == ["card"]
            and sequence_ok
            and all(checks.values())
        )
        return {
            "id": case["id"],
            "name": case["name"],
            "expected_tools": case["expected_tool_sequence"],
            "selected_tools": tool_names(task),
            "task_status": task.get("status"),
            "error_code": task_error(task),
            "tool_sequence_correct": sequence_ok,
            "confirmation_types": first_types,
            "state_checks": checks,
            "pass": passed,
        }

    task, confirmed_types, stale_error = _confirm_until_done(task, case)
    recovery_error: str | None = None
    if case.get("stale_confirmation"):
        stale_detected = stale_error == "subscription_version_conflict"
        recovery_status, recovered = call_api(
            "POST",
            f"/api/v1/agent/tasks/{task['id']}/input",
            {"request_text": "请重新读取后继续暂停腾讯视频会员"},
        )
        recovery_error = error_code(recovered)
        if recovery_status < 400:
            task = recovered
            task, recovery_types, recovery_stale = _confirm_until_done(
                task, case | {"confirmations": 1, "stale_confirmation": False}
            )
            confirmed_types.extend(recovery_types)
            recovery_error = recovery_error or recovery_stale
        else:
            stale_detected = False
        case = case | {"stale_detected": stale_detected}

    sequence = tool_names(task)
    sequence_ok = _tool_sequence_matches(case, sequence)
    checks = _verify_cross_state(case, task)
    expected_confirmation_types = case.get("expected_confirmation_types", [])
    confirmation_ok = (
        not expected_confirmation_types or confirmed_types == expected_confirmation_types
    )
    if case.get("kind") == "clarify_then_execute":
        clarification_ok = True
    else:
        clarification_ok = True
    status_ok = task.get("status") == case.get("expected_status", "completed")
    if case.get("expected_error"):
        checks["expected_error"] = task_error(task) == case["expected_error"]
    if case.get("stale_confirmation"):
        checks["stale_conflict_detected"] = case.get("stale_detected", False)
        checks["recovery_completed"] = task.get("status") == "completed"
        checks["first_write_not_repeated"] = sequence.count("card.freeze") == 1
    passed = (
        sequence_ok
        and confirmation_ok
        and status_ok
        and bool(checks)
        and all(checks.values())
        and clarification_ok
        and recovery_error is None
    )
    return {
        "id": case["id"],
        "name": case["name"],
        "expected_tools": case["expected_tool_sequence"],
        "selected_tools": sequence,
        "task_status": task.get("status"),
        "error_code": task_error(task),
        "tool_sequence_correct": sequence_ok,
        "confirmation_types": confirmed_types,
        "confirmation_sequence_correct": confirmation_ok,
        "initial_clarification": initial_clarification,
        "state_checks": checks,
        "recovery_error": recovery_error,
        "pass": passed,
    }


def request_case(case: dict) -> dict:
    if case.get("phase1e"):
        _reset_eval_database()
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

    if case.get("phase1e"):
        result = request_cross_case(case, task)
        result.setdefault("tool_selection_correct", result.get("tool_sequence_correct", False))
        result.setdefault(
            "parameters_correct",
            all(result.get("state_checks", {}).values())
            if result.get("state_checks")
            else result["pass"],
        )
        expected_status = case.get("expected_status", "completed")
        result.setdefault(
            "task_completed_or_clarified",
            result.get("task_status") == expected_status
            and (
                expected_status in {"completed", "awaiting_input"}
                or result.get("error_code") == case.get("expected_error")
            ),
        )
        result.setdefault("expected_tools", case["expected_tool_sequence"])
        return result

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
        {
            "id": 21,
            "name": "cross_suspicious_charge_two_confirmations",
            "phase1e": True,
            "prompt": (
                "请处置重复扣费提示：先检查异常账单和自动扣费，解释依据，"
                "再冻结相关银行卡并暂停对应订阅。"
            ),
            "expected_tool_sequence": [
                "bill.anomalies",
                "subscription.list",
                "card.freeze",
                "subscription.pause",
            ],
            "confirmations": 2,
            "expected_confirmation_types": ["card", "subscription"],
            "verification": "suspicious_paused",
        },
        {
            "id": 22,
            "name": "cross_payday_transfer_and_investment",
            "phase1e": True,
            "prompt": (
                "发薪日资金调度：先给小林转 200 元，账户预留 3000 元，其余买入适合我的模拟理财。"
            ),
            "expected_tool_sequence": [
                "transfer.accounts",
                "bill.monthly_summary",
                "finance.payday_plan",
                "investment.products",
                "transfer.create",
                "investment.buy",
                "transfer.accounts",
                "investment.portfolio",
            ],
            "confirmations": 2,
            "expected_confirmation_types": ["transfer", "investment_order"],
            "verification": "payday_complete",
        },
        {
            "id": 23,
            "name": "cross_payday_clarification_then_resume",
            "phase1e": True,
            "kind": "clarify_then_execute",
            "prompt": "发薪日帮我规划资金，给小林转一部分，剩余买适合我的理财。",
            "followup": "给小林转 200 元，账户预留 3000 元，其余买入适合我的模拟理财。",
            "expected_tool_sequence": [
                "transfer.accounts",
                "bill.monthly_summary",
                "finance.payday_plan",
                "transfer.create",
                "investment.products",
                "investment.buy",
                "transfer.accounts",
                "investment.portfolio",
            ],
            "confirmations": 2,
            "expected_confirmation_types": ["transfer", "investment_order"],
            "verification": "payday_complete",
        },
        {
            "id": 24,
            "name": "cross_cancel_after_first_confirmation",
            "phase1e": True,
            "kind": "cancel_after_first_confirmation",
            "prompt": "处置重复扣费：检查异常账单与订阅后，冻结关联卡并暂停对应自动扣费。",
            "expected_tool_sequence": [
                "bill.anomalies",
                "subscription.list",
                "card.freeze",
                "subscription.pause",
            ],
            "verification": "suspicious_card_only",
        },
        {
            "id": 25,
            "name": "cross_stale_confirmation_recovery",
            "phase1e": True,
            "stale_confirmation": True,
            "prompt": "检查重复扣费账单和订阅，冻结关联银行卡，并暂停腾讯视频会员自动扣费。",
            "expected_tool_sequence": [
                "bill.anomalies",
                "subscription.list",
                "card.freeze",
                "subscription.pause",
                "subscription.pause",
            ],
            "confirmations": 2,
            "expected_confirmation_types": ["card", "subscription", "subscription"],
            "verification": "suspicious_paused",
        },
        {
            "id": 26,
            "name": "cross_unknown_card_rejected",
            "phase1e": True,
            "prompt": "冻结尾号 9999 的银行卡。",
            "expected_tool_sequence": ["card.freeze"],
            "expected_status": "failed",
            "expected_error": "card_not_found",
            "verification": "failed_target",
        },
        {
            "id": 27,
            "name": "cross_investment_risk_rejected",
            "phase1e": True,
            "prompt": "申购 1000 元成长指数模拟。",
            "expected_tool_sequence": ["investment.products"],
            "forbidden_tools": ["investment.buy"],
            "expected_status": "failed",
            "expected_error": "risk_mismatch",
            "verification": "risk_rejected",
        },
        {
            "id": 28,
            "name": "cross_anomaly_and_subscription_evidence",
            "phase1e": True,
            "prompt": "检查最近的重复扣费提示，并列出相关订阅状态和下次扣款时间。",
            "expected_tool_sequence": ["bill.anomalies", "subscription.list"],
            "verification": "anomaly_subscription_read",
        },
        {
            "id": 29,
            "name": "cross_unknown_payee_clarification",
            "phase1e": True,
            "prompt": "查看我的账户余额后，给张三转 100 元。",
            "expected_tool_sequence": ["transfer.accounts", "transfer.payees"],
            "expected_status": "awaiting_input",
            "forbidden_tools": ["transfer.create"],
            "verification": "no_business_change",
        },
        {
            "id": 30,
            "name": "cross_insufficient_funds_rejected",
            "phase1e": True,
            "prompt": "给小林转 999999 元。",
            "expected_tool_sequence": ["transfer.create"],
            "expected_status": "failed",
            "expected_error": "insufficient_funds",
            "verification": "failed_target",
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
    if any(case.get("phase1e") for case in run_cases):
        try:
            _reset_eval_database()
        except (RuntimeError, ValueError):
            print(json.dumps({"error": "phase1e_test_database_not_safely_configured"}))
            return 2
    results = [request_case(case) for case in run_cases]
    expected_tool_cases = [item for item in results if item["expected_tools"]]
    summary = {
        "model": Settings().llm_model or "configured by server",
        "case_count": len(results),
        "passed": sum(item["pass"] for item in results),
        "expected_terminal_outcome_accuracy": ratio(
            sum(item["pass"] for item in results), len(results)
        ),
        "tool_selection_accuracy": ratio(
            sum(item["tool_selection_correct"] for item in expected_tool_cases),
            len(expected_tool_cases),
        ),
        "parameter_accuracy": ratio(
            sum(item["parameters_correct"] for item in results), len(results)
        ),
        "task_completion_accuracy": ratio(
            sum(
                item["task_completed_or_clarified"]
                for case, item in zip(run_cases, results, strict=True)
                if case.get("expected_status", "completed") in {"completed", "awaiting_input"}
            ),
            sum(
                case.get("expected_status", "completed") in {"completed", "awaiting_input"}
                for case in run_cases
            ),
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
