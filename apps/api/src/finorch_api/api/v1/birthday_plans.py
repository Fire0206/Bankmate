"""Read confirmed synthetic birthday budget intentions."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from finorch_api.application.birthday_plans import list_birthday_plans
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/birthday-plans", tags=["birthday-plans"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]


class BirthdayProductResponse(BaseModel):
    product_code: Literal["flowers", "cake"]
    product_name: str
    unit_price_minor: int
    quantity: int


class BirthdayPlanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    account_id: UUID
    account_label: str
    birthday_on: date
    purchase_on: date
    budget_minor: int
    catalog_total_minor: int
    currency: Literal["CNY"]
    status: Literal["scheduled"]
    due_for_reconfirmation: bool
    funds_held: Literal[False]
    order_placed: Literal[False]
    items: list[BirthdayProductResponse]
    next_action: str


class BirthdayPlansResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BirthdayPlanResponse]


@router.get("", response_model=BirthdayPlansResponse, summary="List owned synthetic birthday plans")
def read_birthday_plans(session: DatabaseSession, actor: CurrentDemoActor) -> BirthdayPlansResponse:
    return BirthdayPlansResponse.model_validate(
        {"items": list_birthday_plans(session, actor_id=actor.user_id)}
    )
