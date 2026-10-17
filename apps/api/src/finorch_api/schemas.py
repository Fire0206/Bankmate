from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: str
    version: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ApiError(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail]
    request_id: str


class ApiErrorResponse(BaseModel):
    error: ApiError
