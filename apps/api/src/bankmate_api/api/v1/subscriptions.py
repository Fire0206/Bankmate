from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from bankmate_api.api.errors import ContractHTTPException
from bankmate_api.api.v1.subscription_schemas import (
    ReminderPreferenceRequest,
    SubscriptionListResponse,
    SubscriptionReminderListResponse,
    SubscriptionResponse,
)
from bankmate_api.application.subscriptions import (
    SubscriptionNotFoundError,
    SubscriptionWriteConflictError,
    generate_due_subscription_reminders,
    list_subscription_reminders,
    list_subscriptions,
    set_subscription_reminder_days,
)
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.security.demo_identity import DemoActor, get_current_demo_actor

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


@router.get(
    "/reminders",
    response_model=SubscriptionReminderListResponse,
    summary="Read upcoming synthetic subscription renewal reminders",
)
def read_reminders(
    session: DatabaseSession, actor: CurrentDemoActor
) -> SubscriptionReminderListResponse:
    items = list_subscription_reminders(session, actor_id=actor.user_id)
    return SubscriptionReminderListResponse.model_validate({"items": [asdict(x) for x in items]})


@router.post(
    "/reminders/refresh",
    response_model=SubscriptionReminderListResponse,
    summary="Generate due in-app synthetic renewal reminders once per billing cycle",
)
def refresh_reminders(
    request: Request, session: DatabaseSession, actor: CurrentDemoActor
) -> SubscriptionReminderListResponse:
    items = generate_due_subscription_reminders(
        session, actor_id=actor.user_id, request_id=request.state.request_id
    )
    return SubscriptionReminderListResponse.model_validate({"items": [asdict(x) for x in items]})


@router.put(
    "/{subscription_id}/reminder-preference",
    response_model=SubscriptionResponse,
    summary="Set one owned synthetic subscription's in-app reminder lead time",
)
def change_reminder_preference(
    subscription_id: UUID,
    body: ReminderPreferenceRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> SubscriptionResponse:
    try:
        result = set_subscription_reminder_days(
            session,
            actor_id=actor.user_id,
            subscription_id=subscription_id,
            days_before=body.days_before,
            expected_version=body.expected_version,
            request_id=request.state.request_id,
        )
    except SubscriptionNotFoundError:
        raise ContractHTTPException(
            404, "subscription_not_found", "没有找到这项自动扣费。"
        ) from None
    except SubscriptionWriteConflictError:
        raise ContractHTTPException(
            409, "subscription_version_conflict", "订阅状态已变化，请刷新后重试。"
        ) from None
    return SubscriptionResponse.model_validate(asdict(result))
