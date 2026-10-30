from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from finorch_api.api.errors import ContractHTTPException
from finorch_api.api.v1.transfer_schemas import (
    AccountBalanceListResponse,
    PayeeCreateRequest,
    PayeeListResponse,
    PayeeResponse,
    SimulatedTransfersResponse,
    SplitBillListResponse,
    TransferDestinationListResponse,
    TransferListResponse,
    TransferResponse,
)
from finorch_api.application.errors import BankingRuleError
from finorch_api.application.transfers import (
    create_payee,
    delete_payee,
    get_transfer,
    list_accounts,
    list_payees,
    list_splits,
    list_transfer_destinations,
    list_transfers,
    simulate_due_transfers,
)
from finorch_api.config import Settings, get_settings
from finorch_api.infrastructure.database import get_db_session
from finorch_api.security.demo_identity import DemoActor, get_current_demo_actor

router = APIRouter(tags=["transfers"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]
CurrentDemoActor = Annotated[DemoActor, Depends(get_current_demo_actor)]
CurrentSettings = Annotated[Settings, Depends(get_settings)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _raise_business_error(error: BankingRuleError) -> None:
    status = (
        404
        if error.code.endswith("_not_found")
        else 409
        if error.code.endswith("conflict")
        else 422
    )
    raise ContractHTTPException(status, error.code, error.public_message) from None


@router.get(
    "/accounts",
    response_model=AccountBalanceListResponse,
    summary="List synthetic account balances",
)
def read_accounts(session: DatabaseSession, actor: CurrentDemoActor) -> AccountBalanceListResponse:
    return AccountBalanceListResponse(
        items=[item.__dict__ for item in list_accounts(session, actor_id=actor.user_id)]
    )


@router.get("/payees", response_model=PayeeListResponse, summary="List saved synthetic recipients")
def read_payees(session: DatabaseSession, actor: CurrentDemoActor) -> PayeeListResponse:
    return PayeeListResponse(
        items=[item.__dict__ for item in list_payees(session, actor_id=actor.user_id)]
    )


@router.get(
    "/transfer-destinations",
    response_model=TransferDestinationListResponse,
    summary="List available synthetic transfer destinations",
)
def read_transfer_destinations(
    session: DatabaseSession, actor: CurrentDemoActor
) -> TransferDestinationListResponse:
    return TransferDestinationListResponse(
        items=[
            item.__dict__ for item in list_transfer_destinations(session, actor_id=actor.user_id)
        ]
    )


@router.post(
    "/payees", response_model=PayeeResponse, status_code=201, summary="Save a synthetic recipient"
)
def add_payee(
    body: PayeeCreateRequest,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> PayeeResponse:
    try:
        value = create_payee(
            session,
            actor_id=actor.user_id,
            display_name=body.display_name,
            destination_account_id=body.destination_account_id,
            phone_number=body.phone_number,
        )
    except BankingRuleError as exc:
        _raise_business_error(exc)
    return PayeeResponse.model_validate(asdict(value))


@router.delete(
    "/payees/{payee_id}", status_code=204, summary="Remove an unused synthetic recipient"
)
def remove_payee(
    payee_id: UUID,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> Response:
    try:
        delete_payee(session, actor_id=actor.user_id, payee_id=payee_id)
    except BankingRuleError as exc:
        _raise_business_error(exc)
    return Response(status_code=204)


@router.get("/transfers", response_model=TransferListResponse, summary="Read transfer history")
def read_transfers(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    limit: Limit = 50,
) -> TransferListResponse:
    return TransferListResponse(
        items=[
            item.__dict__ for item in list_transfers(session, actor_id=actor.user_id, limit=limit)
        ]
    )


@router.get(
    "/transfers/{transfer_id}", response_model=TransferResponse, summary="Read one owned transfer"
)
def read_transfer(
    transfer_id: UUID,
    session: DatabaseSession,
    actor: CurrentDemoActor,
) -> TransferResponse:
    value = get_transfer(session, actor_id=actor.user_id, transfer_id=transfer_id)
    if value is None:
        raise ContractHTTPException(404, "transfer_not_found", "Transfer not found.")
    return TransferResponse.model_validate(asdict(value))


@router.get("/splits", response_model=SplitBillListResponse, summary="Read AA split bills")
def read_splits(
    session: DatabaseSession,
    actor: CurrentDemoActor,
    limit: Limit = 50,
) -> SplitBillListResponse:
    return SplitBillListResponse(
        items=[
            item.__dict__ | {"participants": [part.__dict__ for part in item.participants]}
            for item in list_splits(session, actor_id=actor.user_id, limit=limit)
        ]
    )


@router.post(
    "/simulate-due",
    response_model=SimulatedTransfersResponse,
    summary="Execute previously confirmed due scheduled transfers in the local simulator",
)
def simulate_due(
    request: Request,
    session: DatabaseSession,
    actor: CurrentDemoActor,
    settings: CurrentSettings,
) -> SimulatedTransfersResponse:
    if settings.environment not in {"development", "test"}:
        raise ContractHTTPException(
            403, "demo_only", "Simulation is available only in demo environments."
        )
    items = simulate_due_transfers(
        session,
        actor_id=actor.user_id,
        request_id=request.state.request_id,
    )
    return SimulatedTransfersResponse(
        executed_count=len(items),
        items=[item.__dict__ for item in items],
    )
