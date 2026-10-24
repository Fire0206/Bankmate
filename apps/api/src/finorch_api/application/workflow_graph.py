"""Small persisted dependency graphs for the two supported cross-scenario flows."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from finorch_api.agent.intent import (
    has_explicit_investment_write_intent,
    has_explicit_transfer_write_intent,
    is_planning_only_request,
    requested_card_tool,
    requested_subscription_tool,
)
from finorch_api.agent.runtime import ToolRegistry

WORKFLOW_PLAN_VERSION = 1


@dataclass(frozen=True)
class WorkflowNode:
    node_id: str
    tool_name: str
    depends_on: tuple[str, ...] = ()
    node_type: str = "tool"
    requires_confirmation: bool = False
    failure_policy: str = "stop_dependents_continue_independent"


def validate_workflow_nodes(nodes: Iterable[WorkflowNode]) -> None:
    node_list = tuple(nodes)
    by_id = {node.node_id: node for node in node_list}
    if len(by_id) != len(node_list):
        raise ValueError("Workflow node IDs must be unique.")
    for node in node_list:
        if len(set(node.depends_on)) != len(node.depends_on):
            raise ValueError(f"Workflow node {node.node_id} has duplicate dependencies.")
        missing = set(node.depends_on) - by_id.keys()
        if missing:
            raise ValueError(
                f"Workflow node {node.node_id} has unknown dependencies: {sorted(missing)}"
            )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("Workflow dependency graph must be acyclic.")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in by_id[node_id].depends_on:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in by_id:
        visit(node_id)


def _node(node_id: str, tool_name: str, registry: ToolRegistry, *depends_on: str) -> WorkflowNode:
    spec = registry.get(tool_name)
    if spec is None:
        raise ValueError(f"Workflow references unregistered tool {tool_name!r}.")
    return WorkflowNode(
        node_id=node_id,
        tool_name=tool_name,
        depends_on=tuple(depends_on),
        node_type="tool",
        requires_confirmation=spec.confirmation_requirement != "never",
    )


def _serialize_nodes(nodes: Iterable[WorkflowNode]) -> list[dict[str, Any]]:
    """Keep the persisted/API plan JSON-native rather than leaking Python tuples."""
    return [{**asdict(node), "depends_on": list(node.depends_on)} for node in nodes]


def build_workflow_plan(request_text: str, registry: ToolRegistry) -> dict[str, Any] | None:
    """Build a server-owned DAG only for cross-scenario goals with real dependencies."""
    if is_planning_only_request(request_text):
        return None

    request = request_text.casefold()
    suspicious = any(term in request for term in ("可疑扣款", "重复扣费", "重复扣款"))
    card_tool = requested_card_tool(request_text)
    subscription_tool = requested_subscription_tool(request_text)

    if suspicious and (card_tool == "card.freeze" or subscription_tool == "subscription.pause"):
        nodes: list[WorkflowNode] = []
        nodes.append(_node("charge_evidence", "bill.anomalies", registry))
        if subscription_tool == "subscription.pause":
            nodes.append(_node("subscription_evidence", "subscription.list", registry))
        if card_tool == "card.freeze":
            nodes.append(_node("freeze_related_card", "card.freeze", registry, "charge_evidence"))
        if subscription_tool == "subscription.pause":
            nodes.append(
                _node(
                    "pause_related_subscription",
                    "subscription.pause",
                    registry,
                    "charge_evidence",
                    "subscription_evidence",
                )
            )
        validate_workflow_nodes(nodes)
        return {
            "version": WORKFLOW_PLAN_VERSION,
            "workflow_id": "suspicious_charge_remediation",
            "nodes": _serialize_nodes(nodes),
        }

    transfer_intent = has_explicit_transfer_write_intent(request_text)
    investment_intent = has_explicit_investment_write_intent(request_text)
    if transfer_intent and investment_intent:
        payday = any(term in request for term in ("发薪", "工资", "薪资", "收入到账", "资金调度"))
        nodes = []
        if payday:
            nodes.append(_node("cashflow_plan", "finance.payday_plan", registry))
        nodes.append(_node("suitable_products", "investment.products", registry))
        transfer_dependencies = ["suitable_products"]
        if payday:
            transfer_dependencies.append("cashflow_plan")
        nodes.extend(
            (
                _node("confirmed_transfer", "transfer.create", registry, *transfer_dependencies),
                _node(
                    "confirmed_investment",
                    "investment.buy",
                    registry,
                    "confirmed_transfer",
                    "suitable_products",
                ),
            )
        )
        validate_workflow_nodes(nodes)
        return {
            "version": WORKFLOW_PLAN_VERSION,
            "workflow_id": "payday_transfer_investment" if payday else "transfer_then_investment",
            "nodes": _serialize_nodes(nodes),
        }

    return None


def unsatisfied_dependencies(
    plan: Mapping[str, Any] | None, *, tool_name: str, succeeded_tools: set[str]
) -> tuple[str, ...]:
    if plan is None:
        return ()
    raw_nodes = plan.get("nodes")
    if not isinstance(raw_nodes, list):
        return ("invalid_workflow_plan",)
    nodes = {item.get("node_id"): item for item in raw_nodes if isinstance(item, dict)}
    node = next((item for item in nodes.values() if item.get("tool_name") == tool_name), None)
    if node is None:
        return ()
    dependencies = node.get("depends_on", [])
    if not isinstance(dependencies, list):
        return ("invalid_workflow_plan",)
    missing: list[str] = []
    for dependency_id in dependencies:
        dependency = nodes.get(dependency_id)
        if dependency is None or not isinstance(dependency.get("tool_name"), str):
            missing.append(str(dependency_id))
        elif dependency["tool_name"] not in succeeded_tools:
            missing.append(dependency["tool_name"])
    return tuple(missing)
