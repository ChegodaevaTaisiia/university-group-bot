"""Поздравления: дни рождения и праздники. Утренняя рассылка в супергруппу."""

from __future__ import annotations

import logging
from datetime import date

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.db.models import Holiday, MediaItem, User

log = logging.getLogger(__name__)

# (месяц, день, название, текст)
DEFAULT_HOLIDAYS: list[tuple[int, int, str, str]] = [
    (9, 1, "День знаний", "📚 С Днём знаний! Пусть учебный год будет лёгким, "
     "а сессия закроется без пересдач."),
    (12, 31, "Новый год", "🎄 С наступающим Новым годом! Пусть в новом году "
     "будет меньше дедлайнов и больше автоматов."),
    (1, 25, "Татьянин день", "🎓 С Днём студента! Держитесь, зачётка кормит "
     "только первые два курса."),
    (2, 23, "23 февраля", "🪖 С 23 февраля! Мужской части группы — сил и терпения."),
    (3, 8, "8 марта", "🌷 С 8 марта! Девушкам группы — весны и хорошего настроения."),
]


async def seed_default_holidays(session: AsyncSession) -> None:
    if await session.scalar(select(func.count()).select_from(Holiday)):
        return
    for month, day, title, message in DEFAULT_HOLIDAYS:
        session.add(Holiday(title=title, month=month, day=day, message=message))
    await session.commit()


def _mention(user: User) -> str:
    if user.username:
        return f"@{user.username}"
    return f'<a href="tg://user?id={user.tg_id}">{user.full_name}</a>'


def _age(user: User, today: date) -> int | None:
    if not user.birthday_year:
        return None
    age = today.year - user.birthday_year
    return age


async def _random_birthday_photo(session: AsyncSession) -> str | None:
    return await session.scalar(
        select(MediaItem.file_id)
        .where(MediaItem.kind == "birthday")
        .order_by(func.random())
        .limit(1)
    )


async def run_morning_greetings(bot: Bot, sessionmaker: async_sessionmaker) -> None:
    settings = get_settings()
    if settings.supergroup_id is None:
        return
    today = date.today()

    async with sessionmaker() as session:
        birthdays = list(
            await session.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    User.birthday_day == today.day,
                    User.birthday_month == today.month,
                )
            )
        )
        for user in birthdays:
            age = _age(user, today)
            age_part = f" — {age}! " if age else "! "
            text = (
                f"🎂 Сегодня день рождения у {_mention(user)}{age_part}\n"
                f"Поздравляем! 🥳"
            )
            photo = await _random_birthday_photo(session)
            try:
                if photo:
                    await bot.send_photo(settings.supergroup_id, photo, caption=text)
                else:
                    await bot.send_message(settings.supergroup_id, text)
            except TelegramBadRequest:
                await bot.send_message(settings.supergroup_id, text)

        holidays = list(
            await session.scalars(
                select(Holiday).where(
                    Holiday.is_active.is_(True),
                    Holiday.day == today.day,
                    Holiday.month == today.month,
                )
            )
        )
        for h in holidays:
            try:
                await bot.send_message(settings.supergroup_id, h.message)
            except Exception:  # noqa: BLE001
                log.exception("holiday greeting failed: %s", h.title)


def parse_birthday(text: str) -> tuple[int, int, int | None] | None:
    """«15.09» или «15.09.2005» → (day, month, year|None)."""
    import re

    m = re.match(r"\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{4}))?\s*$", text)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year = int(m.group(3)) if m.group(3) else None
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return None
    if year and not (1950 <= year <= date.today().year):
        return None
    return day, month, year
