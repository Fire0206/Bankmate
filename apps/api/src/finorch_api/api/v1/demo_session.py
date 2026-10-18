from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from finorch_api.application.demo_session import get_demo_session
from finorch_api.config import Settings, get_settings
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/demo/session", tags=["demo identity"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]


class DemoSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    display_name: str
    environment: Literal["development", "test"]
    dataset_version: str
    agent_provider: Literal["fake", "openai-compatible"]


@router.get("", response_model=DemoSessionResponse, summary="Read local synthetic demo identity")
def read_demo_session(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    settings: CurrentSettings,
) -> DemoSessionResponse:
    identity = get_demo_session(session, actor_id=actor.user_id)
    if identity is None:
        raise HTTPException(status_code=503, detail="Demo identity is not seeded.")
    return DemoSessionResponse(
        user_id=identity.user_id,
        display_name=identity.display_name,
        environment=settings.environment,
        dataset_version=identity.dataset_version,
        agent_provider=settings.agent_provider,
    )
