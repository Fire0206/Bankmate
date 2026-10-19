from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from finorch_api.api.errors import ContractHTTPException
from finorch_api.api.v1.financial_insights_schemas import (
    FinancialRecommendationsResponse,
    PaydayPlanPreviewRequest,
    PaydayPlanPreviewResponse,
)
from finorch_api.application.cashflow import plan_payday_allocation
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.financial_insights import get_financial_recommendations
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(tags=["financial insights"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


@router.get(
    "/financial-insights/recommendations",
    response_model=FinancialRecommendationsResponse,
    summary="Read deterministic recommendations from synthetic financial data",
)
def read_recommendations(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    month: Month = None,
) -> FinancialRecommendationsResponse:
    try:
        result = get_financial_recommendations(session, actor_id=actor.user_id, month=month)
    except ValueError as exc:
        raise ContractHTTPException(422, "invalid_month", str(exc)) from None
    return FinancialRecommendationsResponse.model_validate(asdict(result))


@router.post(
    "/cashflow/payday-plan-preview",
    response_model=PaydayPlanPreviewResponse,
    summary="Preview a synthetic payday allocation without changing balances",
)
def preview_payday_plan(
    body: PaydayPlanPreviewRequest,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> PaydayPlanPreviewResponse:
    try:
        result = plan_payday_allocation(
            session,
            actor_id=actor.user_id,
            recipient_name=body.recipient_name,
            transfer_amount_minor=body.transfer_amount_minor,
            reserve_amount_minor=body.reserve_amount_minor,
            source_account_label=body.source_account_label,
            month=body.month,
        )
    except BankingRuleError as exc:
        status = 404 if exc.code.endswith("_not_found") else 422
        raise ContractHTTPException(status, exc.code, exc.public_message) from None
    except ValueError as exc:
        raise ContractHTTPException(422, "invalid_month", str(exc)) from None
    return PaydayPlanPreviewResponse.model_validate(asdict(result))
