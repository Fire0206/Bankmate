"""Issue a one-time simulated verification code in the local terminal.

This is deliberately separate from the Agent API and its tool registry. It is
only a demo channel, not a production authentication factor.
"""

import argparse
from uuid import UUID

from sqlalchemy import select

from finorch_api.application.transactions import write_transaction
from finorch_api.config import get_settings
from finorch_api.infrastructure.database import get_session_factory
from finorch_api.infrastructure.models import ConfirmationChallenge, utc_now
from finorch_api.security.verification import issue_demo_code


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Issue a local simulated OTP for a pending action."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--confirmation-id", type=UUID)
    selection.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        parser.error("Simulated verification is available only in development or test.")
    factory = get_session_factory(settings.database_url)
    try:
        with factory() as session:
            with write_transaction(session, immediate=True):
                confirmation_id = args.confirmation_id
                if args.latest:
                    challenge = session.scalar(
                        select(ConfirmationChallenge)
                        .where(
                            ConfirmationChallenge.actor_id == settings.demo_user_id,
                            ConfirmationChallenge.status == "pending",
                            ConfirmationChallenge.expires_at > utc_now(),
                        )
                        .order_by(ConfirmationChallenge.created_at.desc())
                    )
                    if challenge is None:
                        raise ValueError("No pending confirmation for the configured demo actor.")
                    confirmation_id = challenge.id
                _, code = issue_demo_code(
                    session,
                    actor_id=settings.demo_user_id,
                    confirmation_id=confirmation_id,
                    now=utc_now(),
                )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Local demo verification code: {code} (valid for up to 3 minutes)")


if __name__ == "__main__":
    main()
