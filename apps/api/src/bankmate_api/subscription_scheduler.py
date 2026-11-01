"""Local, database-backed in-app subscription reminder scheduler."""

from __future__ import annotations

import asyncio
import logging

from bankmate_api.application.subscriptions import generate_due_subscription_reminders
from bankmate_api.config import Settings
from bankmate_api.infrastructure.database import get_session_factory

logger = logging.getLogger("bankmate.api.subscription_scheduler")


def run_subscription_reminder_tick(settings: Settings) -> int:
    """Persist due reminders for the configured synthetic demo actor once."""
    factory = get_session_factory(settings.database_url)
    with factory() as session:
        reminders = generate_due_subscription_reminders(
            session,
            actor_id=settings.demo_user_id,
            request_id="subscription-reminder-scheduler",
            now=settings.demo_now,
        )
    return len(reminders)


async def run_subscription_reminder_scheduler(settings: Settings) -> None:
    """Poll simulated billing dates and persist idempotent in-app notices."""
    while True:
        try:
            created = await asyncio.to_thread(run_subscription_reminder_tick, settings)
            if created:
                logger.info("Created synthetic subscription reminders", extra={"count": created})
        except Exception as exc:
            logger.warning(
                "Synthetic subscription reminder scheduler tick failed",
                extra={"error_type": type(exc).__name__},
            )
        await asyncio.sleep(settings.subscription_reminder_scheduler_interval_seconds)
