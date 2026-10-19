from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from finorch_api.api.v1.subscription_schemas import SubscriptionListResponse
from finorch_api.application.subscriptions import list_subscriptions
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]


@router.get(
    "", response_model=SubscriptionListResponse, summary="List synthetic recurring subscriptions"
)
def read_subscriptions(
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> SubscriptionListResponse:
    view = list_subscriptions(session, actor_id=actor.user_id)
    return SubscriptionListResponse.model_validate(asdict(view))
