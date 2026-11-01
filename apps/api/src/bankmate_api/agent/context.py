from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from bankmate_api.infrastructure.models import AgentTask, TaskStep, ToolExecution


@dataclass(frozen=True)
class ToolCallContext:
    session: Session
    actor_id: UUID
    task: AgentTask
    step: TaskStep
    execution: ToolExecution
    request_id: str
