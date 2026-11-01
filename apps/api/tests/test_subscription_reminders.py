from datetime import UTC, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from bankmate_api.agent.providers import ProviderSelection
from bankmate_api.agent.runtime import FakeProvider
from bankmate_api.api.v1.agent import get_provider_selection
from bankmate_api.application.subscriptions import (
    generate_due_subscription_reminders,
    list_subscription_reminders,
)
from bankmate_api.config import Settings
from bankmate_api.infrastructure.database import get_db_session
from bankmate_api.infrastructure.models import Account, AuditEvent, Subscription, utc_now
from bankmate_api.main import app
from bankmate_api.security.demo_identity import (
    DEMO_USER_ONE_ID,
    DEMO_USER_TWO_ID,
    DemoActor,
    get_current_demo_actor,
)
from bankmate_api.subscription_scheduler import run_subscription_reminder_tick


def _active_subscription(session, actor_id):
    from bankmate_api.infrastructure.models import Account

    return session.scalar(
        select(Subscription)
        .join(Account, Account.id == Subscription.account_id)
        .where(Account.demo_user_id == actor_id, Subscription.status == "active")
        .limit(1)
    )


def test_reminders_are_actor_scoped_and_once_per_billing_cycle(seeded_database) -> None:
    with seeded_database.session_factory() as session:
        subscription = _active_subscription(session, DEMO_USER_ONE_ID)
        assert subscription is not None
        subscription_id = subscription.id
        charge_at = subscription.next_charge_at.replace(tzinfo=UTC)
    now = charge_at - timedelta(days=2)

    with seeded_database.session_factory() as session:
        upcoming = list_subscription_reminders(session, actor_id=DEMO_USER_ONE_ID, now=now)
        assert subscription_id in {item.subscription_id for item in upcoming}
        assert not any(item.delivered for item in upcoming)
        other = list_subscription_reminders(session, actor_id=DEMO_USER_TWO_ID, now=now)
        assert subscription_id not in {item.subscription_id for item in other}

    with seeded_database.session_factory() as session:
        first = generate_due_subscription_reminders(
            session, actor_id=DEMO_USER_ONE_ID, request_id="reminder-first", now=now
        )
        assert subscription_id in {item.subscription_id for item in first}
    with seeded_database.session_factory() as session:
        second = generate_due_subscription_reminders(
            session, actor_id=DEMO_USER_ONE_ID, request_id="reminder-retry", now=now
        )
        assert second == ()
        delivered = list_subscription_reminders(session, actor_id=DEMO_USER_ONE_ID, now=now)
        assert next(item for item in delivered if item.subscription_id == subscription_id).delivered
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.event_type == "subscription.renewal_reminder_created",
                    AuditEvent.resource_id == subscription_id,
                )
            )
            == 1
        )

    with seeded_database.session_factory.begin() as session:
        subscription = session.get(Subscription, subscription_id)
        assert subscription is not None
        subscription.next_charge_at = charge_at + timedelta(days=30)
        subscription.status = "paused"
    with seeded_database.session_factory() as session:
        paused = generate_due_subscription_reminders(
            session,
            actor_id=DEMO_USER_ONE_ID,
            request_id="reminder-paused",
            now=charge_at + timedelta(days=28),
        )
        assert paused == ()
    with seeded_database.session_factory.begin() as session:
        subscription = session.get(Subscription, subscription_id)
        assert subscription is not None
        subscription.status = "active"
    with seeded_database.session_factory() as session:
        next_cycle = generate_due_subscription_reminders(
            session,
            actor_id=DEMO_USER_ONE_ID,
            request_id="reminder-next-cycle",
            now=charge_at + timedelta(days=28),
        )
        assert subscription_id in {item.subscription_id for item in next_cycle}


def test_reminder_preference_api_checks_owner_version_and_validation(seeded_database) -> None:
    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    app.dependency_overrides[get_provider_selection] = lambda: ProviderSelection(
        FakeProvider(), "fake"
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.get("/api/v1/subscriptions")
            assert first.status_code == 200, first.text
            own = first.json()["items"][0]
            response = client.put(
                f"/api/v1/subscriptions/{own['id']}/reminder-preference",
                json={"days_before": 5, "expected_version": own["version"]},
            )
            assert response.status_code == 200, response.text
            changed = response.json()
            assert changed["reminder_days_before"] == 5
            assert changed["version"] == own["version"] + 1
            retry = client.put(
                f"/api/v1/subscriptions/{own['id']}/reminder-preference",
                json={"days_before": 5, "expected_version": own["version"]},
            )
            assert retry.status_code == 200
            assert retry.json()["version"] == changed["version"]
            stale = client.put(
                f"/api/v1/subscriptions/{own['id']}/reminder-preference",
                json={"days_before": 6, "expected_version": own["version"]},
            )
            assert stale.status_code == 409
            invalid = client.put(
                f"/api/v1/subscriptions/{own['id']}/reminder-preference",
                json={"days_before": 31, "expected_version": changed["version"]},
            )
            assert invalid.status_code == 422

            app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_TWO_ID)
            denied = client.put(
                f"/api/v1/subscriptions/{own['id']}/reminder-preference",
                json={"days_before": 4, "expected_version": 1},
            )
            assert denied.status_code == 404
            app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
            agent = client.post(
                "/api/v1/agent/tasks",
                json={
                    "request_text": "我有哪些即将续费的提醒？",
                    "conversation_id": "30000000-0000-4000-8000-000000000099",
                },
                headers={"Idempotency-Key": "reminder-agent-read"},
            )
            assert agent.status_code == 200, agent.text
            task = agent.json()
            assert task["status"] == "completed", task
            assert "subscription.reminders" in [step["tool_name"] for step in task["steps"]]
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)
        app.dependency_overrides.pop(get_provider_selection, None)


def test_refresh_api_generates_only_once_from_server_clock(seeded_database) -> None:
    with seeded_database.session_factory.begin() as session:
        subscription = _active_subscription(session, DEMO_USER_ONE_ID)
        assert subscription is not None
        subscription_id = subscription.id
        subscription.next_charge_at = utc_now() + timedelta(days=1)

    def override_session():
        with seeded_database.session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_current_demo_actor] = lambda: DemoActor(DEMO_USER_ONE_ID)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.post("/api/v1/subscriptions/reminders/refresh")
            assert first.status_code == 200, first.text
            assert subscription_id in {
                UUID(item["subscription_id"]) for item in first.json()["items"]
            }
            assert all(item["delivered"] for item in first.json()["items"])
            second = client.post("/api/v1/subscriptions/reminders/refresh")
            assert second.status_code == 200
            assert second.json()["items"] == []
            current = client.get("/api/v1/subscriptions/reminders")
            assert current.status_code == 200
            assert any(
                item["subscription_id"] == str(subscription_id) and item["delivered"]
                for item in current.json()["items"]
            )
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(get_current_demo_actor, None)


def test_development_scheduler_persists_due_reminders_idempotently(seeded_database) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime(2030, 4, 1, 12, tzinfo=UTC)
    with seeded_database.session_factory.begin() as session:
        rows = list(
            session.scalars(
                select(Subscription)
                .join(Account)
                .where(
                    Account.demo_user_id == DEMO_USER_ONE_ID,
                    Subscription.status == "active",
                )
            )
        )
        assert rows
        for row in rows:
            row.next_charge_at = now + timedelta(days=90)
        target = rows[0]
        target.next_charge_at = now + timedelta(days=1)
        target_id = target.id

    settings = Settings(
        _env_file=None,
        environment="development",
        database_url=seeded_database.url,
        demo_user_id=DEMO_USER_ONE_ID,
        demo_now=now,
    )

    assert run_subscription_reminder_tick(settings) == 1
    assert run_subscription_reminder_tick(settings) == 0
    with seeded_database.session_factory() as session:
        target = session.get(Subscription, target_id)
        assert target is not None
        assert target.last_reminded_charge_at == target.next_charge_at
