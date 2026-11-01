import pytest

from bankmate_api.agent.registry import build_tool_registry
from bankmate_api.application.workflow_graph import (
    WorkflowNode,
    build_workflow_plan,
    next_ready_workflow_tool,
    unsatisfied_dependencies,
    validate_workflow_nodes,
)


def test_payday_workflow_persists_acyclic_confirmation_dependencies() -> None:
    plan = build_workflow_plan(
        "发薪日给小林转200元，再申购成长指数1000元理财",
        build_tool_registry(),
    )

    assert plan is not None
    assert plan["workflow_id"] == "payday_transfer_investment"
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    assert nodes["confirmed_transfer"]["depends_on"] == ["suitable_products", "cashflow_plan"]
    assert nodes["confirmed_transfer"]["requires_confirmation"] is True
    assert nodes["confirmed_investment"]["depends_on"] == [
        "confirmed_transfer",
        "suitable_products",
    ]
    assert nodes["confirmed_investment"]["requires_confirmation"] is True


def test_suspicious_charge_actions_require_persisted_evidence_reads() -> None:
    plan = build_workflow_plan(
        "帮我处理可疑扣款，冻结相关卡并暂停对应自动扣费",
        build_tool_registry(),
    )

    assert plan is not None
    nodes = {node["node_id"]: node for node in plan["nodes"]}
    assert nodes["freeze_related_card"]["depends_on"] == ["charge_evidence"]
    assert nodes["pause_related_subscription"]["depends_on"] == [
        "charge_evidence",
        "subscription_evidence",
    ]
    assert unsatisfied_dependencies(
        plan,
        tool_name="card.freeze",
        succeeded_tools=set(),
    ) == ("bill.anomalies",)
    assert unsatisfied_dependencies(
        plan,
        tool_name="subscription.pause",
        succeeded_tools={"bill.anomalies"},
    ) == ("subscription.list",)


@pytest.mark.parametrize(
    "nodes",
    [
        (
            WorkflowNode("duplicate", "a"),
            WorkflowNode("duplicate", "b"),
        ),
        (WorkflowNode("a", "a", ("missing",)),),
        (
            WorkflowNode("a", "a", ("b",)),
            WorkflowNode("b", "b", ("a",)),
        ),
    ],
)
def test_workflow_graph_rejects_duplicate_missing_and_cyclic_nodes(nodes) -> None:
    with pytest.raises(ValueError):
        validate_workflow_nodes(nodes)


def test_planning_only_requests_do_not_create_execution_graph() -> None:
    assert (
        build_workflow_plan(
            "只做发薪日资金测算，给小林转200元，再申购成长指数1000元理财",
            build_tool_registry(),
        )
        is None
    )


def test_birthday_workflow_exposes_only_the_next_dependency_ready_tool() -> None:
    plan = build_workflow_plan("生日安排预算并预约商品", build_tool_registry())

    assert plan is not None
    assert next_ready_workflow_tool(plan, succeeded_tools=set()) == "transfer.accounts"
    assert next_ready_workflow_tool(plan, succeeded_tools={"transfer.accounts"}) == "card.catalog"
    assert (
        next_ready_workflow_tool(plan, succeeded_tools={"transfer.accounts", "card.catalog"})
        == "birthday.plan"
    )
    assert (
        next_ready_workflow_tool(
            plan,
            succeeded_tools={"transfer.accounts", "card.catalog", "birthday.plan"},
        )
        is None
    )


def test_birthday_status_query_does_not_create_a_write_workflow() -> None:
    assert (
        build_workflow_plan(
            "查看已保存的生日赠礼预算和订单状态。",
            build_tool_registry(),
        )
        is None
    )
