from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from finorch_api.api.errors import ContractHTTPException
from finorch_api.api.v1.investment_schemas import (
    InvestmentOrderListResponse,
    InvestmentPortfolioResponse,
    InvestmentProductListResponse,
    RiskAssessmentRequest,
    RiskAssessmentResponse,
    RiskProfileResponse,
    RiskQuestionnaireResponse,
)
from finorch_api.application.investments import (
    get_portfolio,
    get_risk_profile,
    list_orders,
    list_products,
)
from finorch_api.application.risk_assessment import (
    AssessmentIdempotencyConflictError,
    latest_assessment,
    questionnaire_data,
    submit_assessment,
)
from finorch_api.domain.risk_assessment import QUESTIONNAIRE_VERSION, RiskAnswers
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
    "/risk-assessment/questionnaire",
    response_model=RiskQuestionnaireResponse,
    summary="Read the synthetic risk assessment questionnaire",
)
def read_risk_questionnaire(_actor: CurrentDemoActor) -> RiskQuestionnaireResponse:
    return RiskQuestionnaireResponse.model_validate(questionnaire_data())


@router.get(
    "/risk-assessment/latest",
    response_model=RiskAssessmentResponse | None,
    summary="Read the current actor's latest synthetic risk assessment",
)
def read_latest_risk_assessment(
    session: DatabaseSession, actor: CurrentDemoActor
) -> RiskAssessmentResponse | None:
    result = latest_assessment(session, actor_id=actor.user_id)
    return RiskAssessmentResponse.model_validate(result.__dict__) if result else None


@router.post(
    "/risk-assessment",
    response_model=RiskAssessmentResponse,
    summary="Submit a user-completed synthetic risk assessment",
)
def complete_risk_assessment(
    body: RiskAssessmentRequest,
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
) -> RiskAssessmentResponse:
    if body.questionnaire_version != QUESTIONNAIRE_VERSION:
        raise ContractHTTPException(
            409, "assessment_version_changed", "测评问卷已更新，请重新作答。"
        )
    answers: RiskAnswers = {
        "time_horizon": body.time_horizon,
        "loss_tolerance": body.loss_tolerance,
        "liquidity_capacity": body.liquidity_capacity,
        "investment_experience": body.investment_experience,
    }
    try:
        result = submit_assessment(
            session,
            actor_id=actor.user_id,
            answers=answers,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
        )
    except AssessmentIdempotencyConflictError:
        raise ContractHTTPException(
            409, "idempotency_conflict", "该请求标识已用于不同答案。"
        ) from None
    return RiskAssessmentResponse.model_validate(result.__dict__)


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
