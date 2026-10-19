import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from finorch_api.api.v1.agent import router as agent_router
from finorch_api.api.v1.bills import router as bills_router
from finorch_api.api.v1.cards import router as cards_router
from finorch_api.api.v1.demo_session import router as demo_session_router
from finorch_api.api.v1.financial_insights import router as financial_insights_router
from finorch_api.api.v1.health import router as health_router
from finorch_api.api.v1.investments import router as investments_router
from finorch_api.api.v1.subscriptions import router as subscriptions_router
from finorch_api.api.v1.transfers import router as transfers_router
from finorch_api.config import get_settings
from finorch_api.schemas import ApiError, ApiErrorResponse, ErrorDetail

logger = logging.getLogger("finorch.api")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

settings = get_settings()
app = FastAPI(
    title="FinOrch API",
    version=settings.service_version,
    description=(
        "Synthetic banking demo for cards, bills, subscriptions, transfers, and investments. "
        "No real bank, merchant, or payment-network integration."
    ),
    responses={
        401: {"model": ApiErrorResponse, "description": "Authentication required."},
        403: {"model": ApiErrorResponse, "description": "Permission denied."},
        404: {"model": ApiErrorResponse, "description": "Resource not found."},
        409: {"model": ApiErrorResponse, "description": "Request conflicts with current state."},
        422: {"model": ApiErrorResponse, "description": "Request validation failed."},
        500: {"model": ApiErrorResponse, "description": "Unexpected server error."},
        503: {"model": ApiErrorResponse, "description": "Demo identity is unavailable."},
    },
)
app.include_router(health_router, prefix="/api/v1")
app.include_router(cards_router, prefix="/api/v1")
app.include_router(bills_router, prefix="/api/v1")
app.include_router(subscriptions_router, prefix="/api/v1")
app.include_router(transfers_router, prefix="/api/v1")
app.include_router(investments_router, prefix="/api/v1")
app.include_router(agent_router, prefix="/api/v1")
app.include_router(demo_session_router, prefix="/api/v1")
app.include_router(financial_insights_router, prefix="/api/v1")


def request_id_for(request: Request) -> str:
    return getattr(request.state, "request_id", uuid.uuid4().hex)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    payload = ApiErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            details=details or [],
            request_id=request_id_for(request),
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={"X-Request-ID": request_id_for(request)},
    )


@app.middleware("http")
async def attach_request_id(request: Request, call_next: RequestResponseEndpoint) -> Response:
    supplied_request_id = request.headers.get("X-Request-ID", "")
    request.state.request_id = (
        supplied_request_id
        if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
        else uuid.uuid4().hex
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def handle_request_validation(
    request: Request, exception: RequestValidationError
) -> JSONResponse:
    details = [
        ErrorDetail(
            code=str(item.get("type", "invalid_value")),
            message=str(item.get("msg", "Invalid value.")),
            field=".".join(
                str(part)
                for part in item.get("loc", ())
                if part not in {"body", "query", "path", "header"}
            )
            or None,
        )
        for item in exception.errors()
    ]
    return error_response(
        request,
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=details,
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_error(request: Request, exception: StarletteHTTPException) -> JSONResponse:
    code_by_status = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        503: "service_unavailable",
    }
    message_by_status = {
        404: "Resource not found.",
        422: "Request validation failed.",
        503: "Service unavailable.",
    }
    return error_response(
        request,
        status_code=exception.status_code,
        code=getattr(
            exception, "error_code", code_by_status.get(exception.status_code, "http_error")
        ),
        message=getattr(
            exception,
            "public_message",
            message_by_status.get(exception.status_code, "Request failed."),
        ),
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exception: Exception) -> JSONResponse:
    logger.error(
        "Unhandled API error",
        extra={"request_id": request_id_for(request), "error_type": type(exception).__name__},
    )
    return error_response(
        request,
        status_code=500,
        code="internal_error",
        message="An unexpected error occurred.",
    )
