"""Review a synthetic debit-card application in the local demo database."""

import argparse
from uuid import UUID

from bankmate_api.application.card_applications import review_card_application
from bankmate_api.config import get_settings
from bankmate_api.infrastructure.database import get_session_factory
from bankmate_api.infrastructure.models import CardApplication


def main() -> None:
    parser = argparse.ArgumentParser(description="Local simulated debit-card application review.")
    parser.add_argument("application_id", type=UUID)
    parser.add_argument("decision", choices=("approve", "reject"))
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        parser.error("Local card review is available only in development or test.")
    factory = get_session_factory(settings.database_url)
    with factory() as session:
        row = session.get(CardApplication, args.application_id)
        if row is None or row.actor_id != settings.demo_user_id:
            parser.error("Application not found for the configured demo actor.")
        reviewed = review_card_application(
            session, application_id=args.application_id, approve=args.decision == "approve"
        )
    print(
        f"Local demo review: {reviewed.status}; "
        f"new synthetic card suffix: {reviewed.issued_card_suffix or 'none'}"
    )


if __name__ == "__main__":
    main()
