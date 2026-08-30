"""Динамический контекст для ИИ-ассистента: расписание, домашка, дни рождения.

Кладётся в промпт рядом с базой знаний, чтобы бот отвечал на «что задали по матану»
и «когда физика» из своих данных, а не «не знаю».
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.config import get_settings
from bot.db.models import Homework, HomeworkStatus, User
from bot.services.schedule_repo import format_day, lessons_for_week

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]


async def homework_block(session: AsyncSession) -> str:
    today = date.today()
    items = list(
        await session.scalars(
            select(Homework)
            .options(selectinload(Homework.subject))
            .where(Homework.due_date >= today, Homework.due_date <= today + timedelta(days=21))
            .order_by(Homework.due_date)
        )
    )
    if not items:
        return "ДОМАШНИЕ ЗАДАНИЯ: пока ничего не записано."
    lines = ["ДОМАШНИЕ ЗАДАНИЯ (к дате — задание):"]
    for hw in items:
        status = "подтверждено" if hw.status == HomeworkStatus.confirmed else "не подтверждено"
        lines.append(
            f"- {hw.subject.name}, к {hw.due_date.strftime('%d.%m')} ({status}): {hw.text}"
        )
    return "\n".join(lines)


async def schedule_block(session: AsyncSession) -> str:
    settings = get_settings()
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = await lessons_for_week(session, monday, settings.semester_start)
    if not any(d.lessons for d in days):
        return "РАСПИСАНИЕ: не заполнено."
    body = "\n\n".join(format_day(d) for d in days)
    head = f"РАСПИСАНИЕ НА НЕДЕЛЮ (сегодня {today.strftime('%d.%m')}, {WEEKDAYS[today.weekday()]}):"
    return f"{head}\n{body}"


async def birthdays_block(session: AsyncSession) -> str:
    today = date.today()
    users = list(
        await session.scalars(
            select(User).where(User.is_active.is_(True), User.birthday_day.is_not(None))
        )
    )
    if not users:
        return ""

    def days_until(u: User) -> int:
        try:
            d = date(today.year, u.birthday_month, u.birthday_day)
        except ValueError:
            d = date(today.year, u.birthday_month, 28)
        if d < today:
            d = d.replace(year=today.year + 1)
        return (d - today).days

    soon = sorted(users, key=days_until)[:6]
    parts = [
        f"{u.full_name} — {u.birthday_day:02d}.{u.birthday_month:02d} (через {days_until(u)} дн.)"
        for u in soon
    ]
    return "БЛИЖАЙШИЕ ДНИ РОЖДЕНИЯ: " + "; ".join(parts)


async def build_context(session: AsyncSession, kb_block: str) -> str:
    blocks = [
        kb_block,
        await schedule_block(session),
        await homework_block(session),
        await birthdays_block(session),
    ]
    return "\n\n".join(b for b in blocks if b)
