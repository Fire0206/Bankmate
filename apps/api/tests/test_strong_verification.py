from datetime import timedelta
from uuid import uuid4

import pytest
from finorch_api.agent.providers import ProviderSelection
from finorch_api.agent.runtime import FakeProvider
from finorch_api.application.agent import create_agent_task
from finorch_api.application.transactions import write_transaction
from finorch_api.infrastructure.models import ConfirmationChallenge, StrongVerification, utc_now
from finorch_api.security.demo_identity import DEMO_USER_ONE_ID, DEMO_USER_TWO_ID
from finorch_api.security.verification import challenge_risk, consume_demo_code, issue_demo_code
from sqlalchemy import select


@pytest.fixture
def proposal(seeded_database):
    with seeded_database.session_factory() as session:
        task = create_agent_task(
            session,
            actor_id=DEMO_USER_ONE_ID,
            request_text="给小林转 2000 元",
            conversation_id=uuid4(),
            idempotency_key="verification-test",
            request_id="test",
            selection=ProviderSelection(FakeProvider(), "fake"),
        )
        assert task.confirmation is not None
        return seeded_database, task.confirmation.id


def test_demo_code_is_bound_single_use_and_never_stored_in_plaintext(proposal):
    database, challenge_id = proposal
    with database.session_factory() as session, write_transaction(session, immediate=True):
        record, code = issue_demo_code(
            session, actor_id=DEMO_USER_ONE_ID, confirmation_id=challenge_id, now=utc_now()
        )
        assert code != record.code_hash and len(code) == 6
        challenge = session.get(ConfirmationChallenge, challenge_id)
        risk = challenge_risk(session, challenge, utc_now())
        assert risk.level == "red"
        assert (
            consume_demo_code(session, challenge=challenge, decision=risk, code=None, now=utc_now())
            == "strong_verification_required"
        )
        assert (
            consume_demo_code(session, challenge=challenge, decision=risk, code=code, now=utc_now())
            is None
        )
        assert (
            consume_demo_code(session, challenge=challenge, decision=risk, code=code, now=utc_now())
            == "verification_unavailable"
        )


def test_wrong_codes_lock_and_cannot_be_reissued(proposal):
    database, challenge_id = proposal
    with database.session_factory() as session, write_transaction(session, immediate=True):
        record, code = issue_demo_code(
            session, actor_id=DEMO_USER_ONE_ID, confirmation_id=challenge_id, now=utc_now()
        )
        challenge = session.get(ConfirmationChallenge, challenge_id)
        risk = challenge_risk(session, challenge, utc_now())
        wrong = "000000" if code != "000000" else "999999"
        for attempt in range(5):
            result = consume_demo_code(
                session, challenge=challenge, decision=risk, code=wrong, now=utc_now()
            )
            assert result == ("verification_locked" if attempt == 4 else "verification_incorrect")
        assert record.attempts == 5
        with pytest.raises(ValueError):
            issue_demo_code(
                session, actor_id=DEMO_USER_ONE_ID, confirmation_id=challenge_id, now=utc_now()
            )


@pytest.mark.parametrize("change", ["expiry", "parameters", "actor"])
def test_expiry_tampering_and_ownership(proposal, change):
    database, challenge_id = proposal
    with database.session_factory() as session, write_transaction(session, immediate=True):
        if change == "actor":
            with pytest.raises(ValueError):
                issue_demo_code(
                    session, actor_id=DEMO_USER_TWO_ID, confirmation_id=challenge_id, now=utc_now()
                )
            return
        record, code = issue_demo_code(
            session, actor_id=DEMO_USER_ONE_ID, confirmation_id=challenge_id, now=utc_now()
        )
        challenge = session.get(ConfirmationChallenge, challenge_id)
        if change == "expiry":
            record.expires_at = utc_now() - timedelta(seconds=1)
        else:
            challenge.parameters_hash = "0" * 64
        result = consume_demo_code(
            session,
            challenge=challenge,
            decision=challenge_risk(session, challenge, utc_now()),
            code=code,
            now=utc_now(),
        )
        assert result == (
            "verification_expired" if change == "expiry" else "verification_invalidated"
        )


def test_business_rollback_restores_verification_consumption(proposal):
    database, challenge_id = proposal
    with database.session_factory() as session, write_transaction(session, immediate=True):
        _, code = issue_demo_code(
            session, actor_id=DEMO_USER_ONE_ID, confirmation_id=challenge_id, now=utc_now()
        )
    with pytest.raises(RuntimeError), database.session_factory() as session:
        with write_transaction(session, immediate=True):
            challenge = session.get(ConfirmationChallenge, challenge_id)
            assert (
                consume_demo_code(
                    session,
                    challenge=challenge,
                    decision=challenge_risk(session, challenge, utc_now()),
                    code=code,
                    now=utc_now(),
                )
                is None
            )
            raise RuntimeError("business write failed")
    with database.session_factory() as session:
        record = session.scalar(select(StrongVerification))
        assert record.status == "pending" and record.attempts == 0
