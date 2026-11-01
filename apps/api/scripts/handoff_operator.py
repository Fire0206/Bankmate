"""Local-only simulated support operator; no banking operation is performed."""

import argparse
from uuid import UUID

from bankmate_api.application.handoffs import simulate_operator_update
from bankmate_api.config import get_settings
from bankmate_api.infrastructure.database import build_engine
from sqlalchemy.orm import sessionmaker


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a local simulated support ticket")
    parser.add_argument("ticket_id", type=UUID)
    parser.add_argument("status", choices=("in_progress", "resolved"))
    parser.add_argument("--outcome", help="Short non-sensitive resolution summary")
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        parser.error("Simulated operator is only available in development or test")
    engine = build_engine(settings.database_url)
    try:
        with sessionmaker(bind=engine, expire_on_commit=False)() as session:
            result = simulate_operator_update(
                session,
                ticket_id=args.ticket_id,
                target_status=args.status,
                outcome=args.outcome,
                request_id="local-demo-operator",
            )
            print(f"{result.id} {result.status}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
