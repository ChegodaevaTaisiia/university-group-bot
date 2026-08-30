"""APScheduler: минутный тик по напоминаниям + еженедельное обновление базы знаний."""

from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.config import get_settings
from bot.services.greetings import run_morning_greetings
from bot.services.reminders import dispatch_due

log = logging.getLogger(__name__)


def build_scheduler(bot: Bot, sessionmaker: async_sessionmaker) -> AsyncIOScheduler:
    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=str(settings.tz))

    async def tick() -> None:
        try:
            n = await dispatch_due(bot, sessionmaker)
            if n:
                log.info("reminders sent: %s", n)
        except Exception:  # noqa: BLE001
            log.exception("reminder tick failed")

    scheduler.add_job(tick, "interval", minutes=1, id="reminder_tick", coalesce=True,
                      max_instances=1)

    async def greetings() -> None:
        try:
            await run_morning_greetings(bot, sessionmaker)
        except Exception:  # noqa: BLE001
            log.exception("morning greetings failed")

    scheduler.add_job(
        greetings,
        CronTrigger(hour=settings.greetings_hour, minute=0),
        id="morning_greetings",
        misfire_grace_time=3600,
    )

    if settings.kb_school_url:
        async def refresh_kb() -> None:
            try:
                from bot.services.kb_import.university_site import refresh_from_site

                await refresh_from_site(sessionmaker)
            except Exception:  # noqa: BLE001
                log.exception("kb refresh failed")

        scheduler.add_job(
            refresh_kb, CronTrigger(day_of_week="mon", hour=6, minute=0), id="kb_refresh"
        )

    return scheduler
