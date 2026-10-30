from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_text: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID = Field(default_factory=uuid4)


class AgentTaskInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_text: str = Field(min_length=1, max_length=1000)


class AgentConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    parameters_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    verification_code: str | None = Field(default=None, pattern=r"^[0-9]{6}$")


class AgentTaskStepResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    sequence: int
    step_type: str
    status: str
    summary: str
    tool_name: str | None
    error_code: str | None
    result_summary: str | None
    result_data: dict[str, Any] | None


class WorkflowNodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: Literal["tool"]
    tool_name: str
    depends_on: list[str]
    requires_confirmation: bool
    failure_policy: Literal["stop_dependents_continue_independent"]
    status: Literal[
        "pending",
        "running",
        "awaiting_confirmation",
        "succeeded",
        "failed",
        "cancelled",
        "blocked",
    ]
    result_summary: str | None
    error_code: str | None


class WorkflowPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    workflow_id: str
    nodes: list[WorkflowNodeResponse]


class ConfirmationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    resource_type: Literal[
        "card",
        "card_application",
        "birthday_plan",
        "birthday_order",
        "subscription",
        "transfer",
        "split",
        "investment_order",
    ]
    resource_id: UUID
    resource_label: str
    resource_version: int
    current_status: str
    target_status: str
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    policy_version: str
    tool_name: str
    tool_version: str
    card_id: UUID | None = None
    card_suffix: str | None = None
    card_label: str | None = None
    card_version: int | None = None
    subscription_id: UUID | None = None
    merchant: str | None = None
    subscription_version: int | None = None
    details: dict[str, Any] | None = None
    risk_level: Literal["yellow", "red"] = "yellow"
    confirmation_method: Literal["explicit", "demo_otp"] = "explicit"
    risk_rules: list[str] = Field(default_factory=list)


class AgentTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    request_text: str
    provider_mode: Literal["fake", "openai-compatible"]
    status: Literal[
        "pending",
        "planning",
        "awaiting_input",
        "awaiting_confirmation",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    message: str
    error_code: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    steps: list[AgentTaskStepResponse]
    confirmation: ConfirmationResponse | None
    workflow_plan: WorkflowPlanResponse | None


class AgentTaskHistoryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    conversation_id: UUID
    request_text: str
    status: Literal[
        "pending",
        "planning",
        "awaiting_input",
        "awaiting_confirmation",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]
    message: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class AgentTaskHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AgentTaskHistoryItemResponse]


class AgentAuditEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    event_type: str
    resource_type: str
    resource_id: UUID
    tool_execution_id: UUID | None
    outcome: str
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    occurred_at: datetime


class AgentAuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    events: list[AgentAuditEventResponse]
