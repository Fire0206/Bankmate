"""Typed tools for card limits and bounded synthetic catalog purchases."""

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from finorch_api.agent.context import ToolCallContext
from finorch_api.agent.runtime import ToolSpec
from finorch_api.application.card_controls import (
    CATALOG,
    propose_card_controls,
    propose_card_purchase,
)
from finorch_api.application.errors import BankingRuleError
from finorch_api.domain.transfers import InvalidTransferError, parse_money_to_minor


class CardCatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CardCatalogItem(BaseModel):
    product_code: Literal["flowers", "cake"]
    product_name: str
    unit_price_minor: int
    currency: Literal["CNY"] = "CNY"


class CardCatalogOutput(BaseModel):
    items: list[CardCatalogItem]


class CardControlsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_suffix: str = Field(pattern=r"^\d{4}$")
    single_limit_minor: int | None = Field(default=None, gt=0, le=10_000_000, strict=True)
    daily_limit_minor: int | None = Field(default=None, gt=0, le=10_000_000, strict=True)
    online_enabled: bool | None = None

    @model_validator(mode="after")
    def has_change(self):
        supplied = sum(
            item is not None
            for item in (self.single_limit_minor, self.daily_limit_minor, self.online_enabled)
        )
        if supplied != 1:
            raise ValueError("Change exactly one card control per confirmation.")
        return self


class CardPurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    card_suffix: str = Field(pattern=r"^\d{4}$")
    product_code: Literal["flowers", "cake"]
    quantity: int = Field(default=1, ge=1, le=3, strict=True)
    channel: Literal["online", "in_store"] = "online"


class CardControlProposalOutput(BaseModel):
    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    card_id: UUID
    card_suffix: str
    card_label: str
    current_status: str
    target_status: Literal["updated"]
    card_version: int
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["card"]
    resource_id: UUID
    resource_label: str
    resource_version: int
    single_limit_minor: int
    daily_limit_minor: int
    online_enabled: bool


class CardPurchaseProposalOutput(BaseModel):
    status: Literal["awaiting_confirmation"]
    confirmation_required: Literal[True]
    challenge_id: UUID
    card_id: UUID
    card_suffix: str
    card_label: str
    current_status: str
    target_status: Literal["executed"]
    card_version: int
    parameters_hash: str
    idempotency_key: str
    expires_at: datetime
    resource_type: Literal["card"]
    resource_id: UUID
    resource_label: str
    resource_version: int
    product_code: Literal["flowers", "cake"]
    product_name: str
    quantity: int
    channel: Literal["online", "in_store"]
    amount_minor: int


def _catalog(_arguments: BaseModel, _context: ToolCallContext) -> CardCatalogOutput:
    return CardCatalogOutput(
        items=[
            CardCatalogItem(product_code=code, product_name=name, unit_price_minor=price)
            for code, (name, price) in CATALOG.items()
        ]
    )


def _controls(arguments: BaseModel, context: ToolCallContext) -> CardControlProposalOutput:
    typed = CardControlsInput.model_validate(arguments)
    request = context.task.request_text
    if typed.card_suffix not in request:
        raise BankingRuleError("card_target_mismatch", "卡片尾号与用户请求不一致。")
    if typed.online_enabled is not None:
        if not any(word in request for word in ("线上", "网络支付", "网上支付")):
            raise BankingRuleError("card_control_mismatch", "用户未要求修改线上支付开关。")
        expected = any(word in request for word in ("开启", "打开", "允许", "恢复"))
        if expected != typed.online_enabled or not any(
            word in request for word in ("开启", "打开", "允许", "恢复", "关闭", "禁用", "停用")
        ):
            raise BankingRuleError("card_control_mismatch", "线上支付设置与用户请求不一致。")
    else:
        field_name = "单笔" if typed.single_limit_minor is not None else "单日"
        if field_name == "单日" and not any(word in request for word in ("单日", "每日", "每天")):
            raise BankingRuleError("card_control_mismatch", "用户未要求修改每日限额。")
        if field_name == "单笔" and "单笔" not in request:
            raise BankingRuleError("card_control_mismatch", "用户未要求修改单笔限额。")
        money = re.search(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块钱|块)", request)
        try:
            expected_minor = parse_money_to_minor(money.group(1)) if money else None
        except InvalidTransferError:
            expected_minor = None
        target_minor = (
            typed.single_limit_minor
            if typed.single_limit_minor is not None
            else typed.daily_limit_minor
        )
        if expected_minor != target_minor:
            raise BankingRuleError("card_control_mismatch", "限额与用户请求不一致。")
    return CardControlProposalOutput.model_validate(
        propose_card_controls(
            context.session,
            context=context,
            card_suffix=typed.card_suffix,
            single_limit_minor=typed.single_limit_minor,
            daily_limit_minor=typed.daily_limit_minor,
            online_enabled=typed.online_enabled,
        )
    )


def _purchase(arguments: BaseModel, context: ToolCallContext) -> CardPurchaseProposalOutput:
    typed = CardPurchaseInput.model_validate(arguments)
    request = context.task.request_text
    product_name = CATALOG[typed.product_code][0]
    if typed.card_suffix not in request or not any(
        word in request
        for word in (product_name, "鲜花" if typed.product_code == "flowers" else "蛋糕")
    ):
        raise BankingRuleError("card_purchase_mismatch", "商品或银行卡与用户请求不一致。")
    requested_quantity = re.search(
        r"(?<!\d)([1-3])\s*(?:束|个|份|件)\s*(?:模拟)?(?:鲜花|蛋糕)", request
    )
    if typed.quantity != (int(requested_quantity.group(1)) if requested_quantity else 1):
        raise BankingRuleError("card_purchase_mismatch", "商品数量与用户请求不一致。")
    if typed.channel == "in_store" and not any(
        word in request for word in ("线下", "店内", "门店")
    ):
        raise BankingRuleError("card_purchase_mismatch", "用户没有要求线下模拟消费。")
    return CardPurchaseProposalOutput.model_validate(
        propose_card_purchase(
            context.session,
            context=context,
            card_suffix=typed.card_suffix,
            product_code=typed.product_code,
            quantity=typed.quantity,
            channel=typed.channel,
        )
    )


def card_control_tool_specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            name="card.catalog",
            description=(
                "List the two fixed-price synthetic gift products "
                "available for demo card purchases."
            ),
            version="1.0",
            input_model=CardCatalogInput,
            output_model=CardCatalogOutput,
            permission_level="read_only",
            risk_level="low",
            confirmation_requirement="never",
            handler=_catalog,
        ),
        ToolSpec(
            name="card.controls",
            description=(
                "Propose changing an owned synthetic debit card's per-purchase limit, "
                "daily purchase limit, or online purchase switch. Requires confirmation."
            ),
            version="1.0",
            input_model=CardControlsInput,
            output_model=CardControlProposalOutput,
            permission_level="reversible_write",
            risk_level="medium",
            confirmation_requirement="always",
            handler=_controls,
        ),
        ToolSpec(
            name="card.purchase",
            description=(
                "Propose buying a fixed-price synthetic catalog item with an owned card. "
                "The server calculates price and enforces card controls, "
                "balance, confirmation and audit."
            ),
            version="1.0",
            input_model=CardPurchaseInput,
            output_model=CardPurchaseProposalOutput,
            permission_level="high_risk_write",
            risk_level="medium",
            confirmation_requirement="always",
            handler=_purchase,
        ),
    )
