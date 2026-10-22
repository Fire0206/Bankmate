from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch_api.domain.cards import CardStatus
from finorch_api.domain.subscriptions import detect_recurring_subscriptions
from finorch_api.infrastructure.database import Base
from finorch_api.infrastructure.models import (
    Account,
    Card,
    DemoUser,
    InvestmentProduct,
    Payee,
    Subscription,
    Transaction,
)
from finorch_api.security.demo_identity import DEMO_USER_ONE_ID, DEMO_USER_TWO_ID

DATASET_VERSION = "phase3-v1"
_SYNTHETIC_NAMESPACE = UUID("a0000000-0000-4000-8000-000000000001")

_USERS = (
    (DEMO_USER_ONE_ID, "Demo User One", 3),
    (DEMO_USER_TWO_ID, "Demo User Two", 1),
)

_ACCOUNTS = (
    (
        UUID("10000000-0000-4000-8000-000000000001"),
        DEMO_USER_ONE_ID,
        "Everyday account",
        "CNY",
        1_250_000,
    ),
    (
        UUID("10000000-0000-4000-8000-000000000002"),
        DEMO_USER_ONE_ID,
        "Savings account",
        "CNY",
        8_000_000,
    ),
    (
        UUID("10000000-0000-4000-8000-000000000003"),
        DEMO_USER_TWO_ID,
        "Everyday account",
        "CNY",
        642_500,
    ),
)

_CARDS = (
    (
        UUID("20000000-0000-4000-8000-000000000001"),
        UUID("10000000-0000-4000-8000-000000000001"),
        "Everyday debit",
        "1042",
        CardStatus.ACTIVE,
    ),
    (
        UUID("20000000-0000-4000-8000-000000000002"),
        UUID("10000000-0000-4000-8000-000000000002"),
        "Savings debit",
        "4318",
        CardStatus.FROZEN,
    ),
    (
        UUID("20000000-0000-4000-8000-000000000003"),
        UUID("10000000-0000-4000-8000-000000000003"),
        "Travel debit",
        "2729",
        CardStatus.ACTIVE,
    ),
)

_PAYEES = (
    (
        UUID("30000000-0000-4000-8000-000000000001"),
        DEMO_USER_ONE_ID,
        UUID("10000000-0000-4000-8000-000000000003"),
        "小林",
        "19900001042",
    ),
    (
        UUID("30000000-0000-4000-8000-000000000002"),
        DEMO_USER_ONE_ID,
        UUID("10000000-0000-4000-8000-000000000002"),
        "储蓄账户",
        None,
    ),
    (
        UUID("30000000-0000-4000-8000-000000000003"),
        DEMO_USER_TWO_ID,
        UUID("10000000-0000-4000-8000-000000000001"),
        "小林",
        "19900002729",
    ),
)

_PRODUCTS = (
    (
        UUID("40000000-0000-4000-8000-000000000001"),
        "CASH-001",
        "安稳现金管理",
        "货币基金",
        1,
        10_000,
        10_000,
        180,
        0,
        "模拟净值固定，收益率为演示估值。",
    ),
    (
        UUID("40000000-0000-4000-8000-000000000002"),
        "BOND-001",
        "稳健短债组合",
        "债券基金",
        2,
        100_000,
        10_000,
        320,
        90,
        "中低风险短债类模拟产品，收益不保证。",
    ),
    (
        UUID("40000000-0000-4000-8000-000000000003"),
        "INDEX-001",
        "成长指数模拟",
        "指数基金",
        4,
        50_000,
        15_000,
        800,
        0,
        "较高波动的指数类模拟产品，收益不保证。",
    ),
)


def _monthly_transaction_fixtures() -> tuple[tuple[object, ...], ...]:
    fixtures: list[tuple[object, ...]] = []
    account_id = UUID("10000000-0000-4000-8000-000000000001")
    for month, day in ((5, 5), (6, 5), (7, 5), (8, 5), (9, 5), (10, 5)):
        fixtures.append(
            (
                account_id,
                f"video-{month:02d}",
                "expense",
                3_000,
                "腾讯视频会员",
                "订阅",
                datetime(2026, month, day, 2, tzinfo=UTC),
            )
        )
    for month, day in ((5, 12), (6, 12), (7, 12), (8, 12), (9, 12), (10, 12)):
        fixtures.append(
            (
                account_id,
                f"music-{month:02d}",
                "expense",
                1_800,
                "网易云音乐会员",
                "订阅",
                datetime(2026, month, day, 2, tzinfo=UTC),
            )
        )
    for month, day in ((5, 19), (6, 19), (7, 19), (8, 19), (9, 19), (10, 19)):
        fixtures.append(
            (
                account_id,
                f"cloud-{month:02d}",
                "expense",
                800,
                "云盘会员",
                "订阅",
                datetime(2026, month, day, 2, tzinfo=UTC),
            )
        )

    ordinary = (
        ("salary-oct", "income", 650_000, "工资", "收入", datetime(2026, 10, 1, 1, tzinfo=UTC)),
        ("food-oct-1", "expense", 3_680, "小满面馆", "餐饮", datetime(2026, 10, 2, 4, tzinfo=UTC)),
        ("food-oct-2", "expense", 5_280, "邻里超市", "餐饮", datetime(2026, 10, 8, 11, tzinfo=UTC)),
        ("food-oct-3", "expense", 2_480, "咖啡工坊", "餐饮", datetime(2026, 10, 16, 3, tzinfo=UTC)),
        (
            "transport-oct-1",
            "expense",
            560,
            "深圳地铁",
            "交通",
            datetime(2026, 10, 3, 0, tzinfo=UTC),
        ),
        (
            "transport-oct-2",
            "expense",
            1_200,
            "网约车",
            "交通",
            datetime(2026, 10, 9, 12, tzinfo=UTC),
        ),
        (
            "shopping-oct",
            "expense",
            12_900,
            "日用百货",
            "购物",
            datetime(2026, 10, 11, 7, tzinfo=UTC),
        ),
        ("home-oct", "expense", 1_800_000, "房租", "住房", datetime(2026, 10, 1, 0, tzinfo=UTC)),
        (
            "anomaly-oct",
            "expense",
            168_800,
            "星河数码",
            "数码",
            datetime(2026, 10, 17, 6, tzinfo=UTC),
        ),
        (
            "video-duplicate-oct",
            "expense",
            3_000,
            "腾讯视频会员",
            "订阅",
            datetime(2026, 10, 5, 2, 10, tzinfo=UTC),
        ),
        ("food-sep", "expense", 4_260, "小满面馆", "餐饮", datetime(2026, 9, 8, 4, tzinfo=UTC)),
        ("transport-sep", "expense", 720, "深圳地铁", "交通", datetime(2026, 9, 12, 3, tzinfo=UTC)),
    )
    fixtures.extend((account_id, *item) for item in ordinary)
    fixtures.append(
        (
            UUID("10000000-0000-4000-8000-000000000003"),
            "user-two-food",
            "expense",
            3_600,
            "海边食堂",
            "餐饮",
            datetime(2026, 10, 4, 5, tzinfo=UTC),
        )
    )
    return tuple(fixtures)


_TRANSACTIONS = _monthly_transaction_fixtures()


def _add_missing(session: Session, model: type[Base], entity_id: UUID, **values: object) -> None:
    if session.get(model, entity_id) is None:
        session.add(model(id=entity_id, **values))


def seed_demo_data(session: Session) -> None:
    """Insert missing deterministic fixtures; the caller owns the transaction."""
    for user_id, display_name, risk_level in _USERS:
        user = session.get(DemoUser, user_id)
        if user is None:
            session.add(
                DemoUser(
                    id=user_id,
                    display_name=display_name,
                    dataset_version=DATASET_VERSION,
                    risk_level=risk_level,
                )
            )
        else:
            user.dataset_version = DATASET_VERSION
            user.risk_level = risk_level
    session.flush()

    for account_id, user_id, label, currency, opening_balance_minor in _ACCOUNTS:
        _add_missing(
            session,
            Account,
            account_id,
            demo_user_id=user_id,
            label=label,
            currency=currency,
            opening_balance_minor=opening_balance_minor,
            balance_minor=opening_balance_minor,
            version=1,
        )
    session.flush()

    for payee_id, user_id, destination_account_id, display_name, phone_number in _PAYEES:
        _add_missing(
            session,
            Payee,
            payee_id,
            actor_id=user_id,
            destination_account_id=destination_account_id,
            display_name=display_name,
            normalized_name="".join(display_name.split()).casefold(),
            phone_number=phone_number,
        )
        saved_payee = session.get(Payee, payee_id)
        if saved_payee is not None and saved_payee.phone_number is None and phone_number:
            bound = session.scalar(
                select(Payee.id).where(
                    Payee.actor_id == user_id,
                    Payee.phone_number == phone_number,
                    Payee.id != payee_id,
                )
            )
            if bound is None:
                saved_payee.phone_number = phone_number
    for (
        product_id,
        code,
        name,
        category,
        risk_level,
        minimum_amount_minor,
        unit_price_minor,
        annual_yield_bps,
        term_days,
        description,
    ) in _PRODUCTS:
        _add_missing(
            session,
            InvestmentProduct,
            product_id,
            code=code,
            name=name,
            category=category,
            risk_level=risk_level,
            minimum_amount_minor=minimum_amount_minor,
            unit_price_minor=unit_price_minor,
            annual_yield_bps=annual_yield_bps,
            term_days=term_days,
            currency="CNY",
            description=description,
        )

    for card_id, account_id, label, suffix, status in _CARDS:
        _add_missing(
            session,
            Card,
            card_id,
            account_id=account_id,
            label=label,
            card_suffix=suffix,
            status=status,
            version=1,
        )
    session.flush()

    for (
        account_id,
        reference,
        direction,
        amount_minor,
        merchant,
        category,
        occurred_at,
    ) in _TRANSACTIONS:
        transaction_id = uuid5(_SYNTHETIC_NAMESPACE, str(reference))
        card_id = next((item[0] for item in _CARDS if item[1] == account_id), None)
        _add_missing(
            session,
            Transaction,
            transaction_id,
            account_id=account_id,
            card_id=card_id,
            synthetic_ref=str(reference),
            direction=direction,
            amount_minor=amount_minor,
            currency="CNY",
            merchant=merchant,
            category=category,
            description=f"模拟{category}流水",
            occurred_at=occurred_at,
        )
    session.flush()

    transactions = list(session.scalars(select(Transaction).order_by(Transaction.occurred_at)))
    for candidate in detect_recurring_subscriptions(transactions):
        subscription_id = uuid5(
            _SYNTHETIC_NAMESPACE, f"subscription:{candidate.account_id}:{candidate.merchant_key}"
        )
        if session.get(Subscription, subscription_id) is None:
            session.add(
                Subscription(
                    id=subscription_id,
                    account_id=candidate.account_id,
                    merchant_key=candidate.merchant_key,
                    merchant=candidate.merchant,
                    amount_minor=candidate.amount_minor,
                    currency=candidate.currency,
                    billing_cycle="monthly",
                    status="active",
                    next_charge_at=candidate.next_charge_at,
                    source_transaction_ids=list(candidate.source_transaction_ids),
                    version=1,
                )
            )
    session.flush()
