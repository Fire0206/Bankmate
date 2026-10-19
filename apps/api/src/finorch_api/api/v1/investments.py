from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from finorch_api.api.v1.investment_schemas import (
    InvestmentOrderListResponse,
    InvestmentPortfolioResponse,
    InvestmentProductListResponse,
    RiskProfileResponse,
)
from finorch_api.application.investments import (
    get_portfolio,
    get_risk_profile,
    list_orders,
    list_products,
)
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(prefix="/investments", tags=["investments"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
Risk = Annotated[int | None, Query(ge=1, le=5)]
Category = Annotated[str | None, Query(max_length=48)]


@router.get("/profile", response_model=RiskProfileResponse, summary="Read demo risk profile")
def read_risk_profile(session: DatabaseSession, actor: CurrentDemoActor) -> RiskProfileResponse:
    risk_level, risk_label = get_risk_profile(session, actor_id=actor.user_id)
    return RiskProfileResponse(risk_level=risk_level, risk_label=risk_label)


@router.get(
    "/products",
    response_model=InvestmentProductListResponse,
    summary="List synthetic investment products",
)
def read_products(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    category: Category = None,
    maximum_risk_level: Risk = None,
) -> InvestmentProductListResponse:
    risk_level, risk_label = get_risk_profile(session, actor_id=actor.user_id)
    items = list_products(
        session,
        actor_id=actor.user_id,
        category=category,
        maximum_risk_level=maximum_risk_level,
    )
    return InvestmentProductListResponse(
        items=[asdict(item) for item in items],
        risk_level=risk_level,
        risk_label=risk_label,
    )


@router.get(
    "/portfolio",
    response_model=InvestmentPortfolioResponse,
    summary="Read simulated portfolio and assets",
)
def read_portfolio(
    session: DatabaseSession, actor: CurrentDemoActor
) -> InvestmentPortfolioResponse:
    value = get_portfolio(session, actor_id=actor.user_id)
    return InvestmentPortfolioResponse.model_validate(asdict(value))


@router.get(
    "/orders",
    response_model=InvestmentOrderListResponse,
    summary="Read simulated investment orders",
)
def read_orders(session: DatabaseSession, actor: CurrentDemoActor) -> InvestmentOrderListResponse:
    return InvestmentOrderListResponse(
        items=[asdict(item) for item in list_orders(session, actor_id=actor.user_id)]
    )
