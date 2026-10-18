from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from finorch_api.infrastructure.models import DemoUser


@dataclass(frozen=True)
class DemoSessionView:
    user_id: UUID
    display_name: str
    dataset_version: str


def get_demo_session(session: Session, *, actor_id: UUID) -> DemoSessionView | None:
    user = session.get(DemoUser, actor_id)
    if user is None:
        return None
    return DemoSessionView(
        user_id=user.id,
        display_name=user.display_name,
        dataset_version=user.dataset_version,
    )
