from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from finorch_api.api.errors import ContractHTTPException
from finorch_api.api.v1.bill_schemas import (
    AnnualBillResponse,
    BillSummaryResponse,
    TransactionPageResponse,
)
from finorch_api.application.bills import get_annual_report, get_monthly_summary, list_transactions
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(tags=["bills"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


@router.get(
    "/transactions", response_model=TransactionPageResponse, summary="List synthetic transactions"
)
def read_transactions(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    month: Month = None,
    category: Annotated[str | None, Query(max_length=48)] = None,
    merchant: Annotated[str | None, Query(max_length=120)] = None,
    direction: Literal["income", "expense"] | None = None,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> TransactionPageResponse:
    try:
        page = list_transactions(
            session,
            actor_id=actor.user_id,
            month=month,
            category=category,
            merchant=merchant,
            direction=direction,
            offset=offset,
            limit=limit,
        )
    except ValueError as exc:
        raise ContractHTTPException(422, "invalid_month", str(exc)) from None
    return TransactionPageResponse.model_validate(asdict(page))


@router.get(
    "/bills/summary", response_model=BillSummaryResponse, summary="Read a monthly bill summary"
)
def read_bill_summary(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    month: Month = None,
    category: Annotated[str | None, Query(max_length=48)] = None,
) -> BillSummaryResponse:
    try:
        summary = get_monthly_summary(
            session, actor_id=actor.user_id, month=month, category=category
        )
    except ValueError as exc:
        raise ContractHTTPException(422, "invalid_month", str(exc)) from None
    return BillSummaryResponse.model_validate(asdict(summary))


@router.get(
    "/bills/annual",
    response_model=AnnualBillResponse,
    summary="Read an annual synthetic bill report",
)
def read_annual_bill(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    year: Annotated[int, Query(ge=2000, le=2100)],
) -> AnnualBillResponse:
    report = get_annual_report(session, actor_id=actor.user_id, year=year)
    return AnnualBillResponse.model_validate(asdict(report))
