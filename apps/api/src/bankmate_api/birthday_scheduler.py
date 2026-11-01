"""One-shot, database-backed scheduler for due synthetic birthday orders.

Run this module periodically from Windows Task Scheduler or cron. Each due
transition is stored on the order row and can be safely retried after a restart.
The command only creates a due reminder; it never authorizes or pays an order.
"""

import argparse
from datetime import UTC, datetime

from bankmate_api.application.birthday_plans import dispatch_due_birthday_orders
from bankmate_api.config import get_settings
from bankmate_api.infrastructure.database import get_session_factory


def _parse_now(value: str | None, configured: datetime | None) -> datetime:
    if value is None:
        result = configured or datetime.now(UTC)
    else:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("--now must include a UTC offset, for example 2026-11-18T09:00:00+08:00")
    return result.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Create due reminders for stored synthetic birthday orders; does not pay orders."
        )
    )
    parser.add_argument(
        "--now",
        help=(
            "Optional simulation time with UTC offset; otherwise uses "
            "BANKMATE_DEMO_NOW or current UTC."
        ),
    )
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment not in {"development", "test"}:
        parser.error("Birthday scheduler is limited to local development and test environments.")
    try:
        current = _parse_now(args.now, settings.demo_now)
    except ValueError as exc:
        parser.error(str(exc))
    factory = get_session_factory(settings.database_url)
    with factory() as session:
        count = dispatch_due_birthday_orders(session, now=current)
    print(f"Birthday scheduler: {count} due reminder(s) created; no order was paid.")


if __name__ == "__main__":
    main()
