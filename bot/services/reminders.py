"""Создание напоминаний и их диспетчеризация (вызывается минутным тиком)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot import texts
from bot.config import get_settings
from bot.db.models import Reminder, ReminderRepeat, User

log = logging.getLogger(__name__)

LEAD_CHOICES = [
    ("В момент события", 0),
    ("За 15 минут", 15),
    ("За 1 час", 60),
    ("За день", 60 * 24),
]
REPEAT_CHOICES = [
    ("Не повторять", ReminderRepeat.none),
    ("Каждый день", ReminderRepeat.daily),
    ("Каждую неделю", ReminderRepeat.weekly),
]


def _advance(fire_at: datetime, repeat: ReminderRepeat) -> datetime | None:
    if repeat == ReminderRepeat.daily:
        step = timedelta(days=1)
    elif repeat == ReminderRepeat.weekly:
        step = timedelta(weeks=1)
    else:
        return None
    now = datetime.now(UTC)
    nxt = fire_at + step
    while nxt <= now:
        nxt += step
    return nxt


def _in_dnd(user: User, local_now: datetime) -> bool:
    prefs = user.prefs
    if not prefs or not prefs.dnd_start or not prefs.dnd_end:
        return False
    t = local_now.time()
    if prefs.dnd_start <= prefs.dnd_end:
        return prefs.dnd_start <= t < prefs.dnd_end
    return t >= prefs.dnd_start or t < prefs.dnd_end  # окно через полночь


async def dispatch_due(bot: Bot, sessionmaker: async_sessionmaker) -> int:
    """Отправляет наступившие напоминания. Возвращает количество отправленных."""
    settings = get_settings()
    now = datetime.now(UTC)
    sent = 0

    async with sessionmaker() as session:
        stmt = (
            select(Reminder)
            .where(Reminder.is_active.is_(True))
            .where(Reminder.fire_at <= now)
        )
        due = list(await session.scalars(stmt))
        for rem in due:
            user = await session.get(User, rem.user_id) if rem.user_id else None
            if user is None or not user.is_active:
                rem.is_active = False
                continue

            local_now = now.astimezone(settings.tz)
            if _in_dnd(user, local_now):
                # перенесём на конец окна тишины
                rem.fire_at = now + timedelta(minutes=30)
                continue

            try:
                await bot.send_message(
                    user.tg_id, texts.REM_FIRED.format(title=rem.title)
                )
                sent += 1
            except TelegramForbiddenError:
                user.is_active = False
            except Exception as e:  # noqa: BLE001
                log.warning("reminder send failed for %s: %s", user.tg_id, e)
                continue

            rem.last_fired_at = now
            nxt = _advance(rem.fire_at, rem.repeat)
            if nxt is None:
                rem.is_active = False
            else:
                rem.fire_at = nxt

        await session.commit()
    return sent
