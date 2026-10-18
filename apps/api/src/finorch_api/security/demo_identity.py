from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException

from finorch_api.config import Settings, get_settings

DEMO_USER_ONE_ID = UUID("00000000-0000-4000-8000-000000000001")
DEMO_USER_TWO_ID = UUID("00000000-0000-4000-8000-000000000002")


@dataclass(frozen=True)
class DemoActor:
    user_id: UUID


def get_current_demo_actor(settings: Annotated[Settings, Depends(get_settings)]) -> DemoActor:
    if settings.environment not in {"development", "test"}:
        raise HTTPException(status_code=503, detail="Demo identity is unavailable.")
    return DemoActor(user_id=settings.demo_user_id)
