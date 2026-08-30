"""Работа с расписанием: чётность недели и выборка пар на день/неделю."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import Lesson, WeekParity

WEEKDAY_NAMES = [
    "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"
]


def week_parity(on: date, semester_start: date) -> WeekParity:
    """odd = 1-я неделя семестра (числитель), even = 2-я (знаменатель)."""
    monday_start = semester_start - timedelta(days=semester_start.weekday())
    monday_on = on - timedelta(days=on.weekday())
    weeks = (monday_on - monday_start).days // 7
    return WeekParity.odd if weeks % 2 == 0 else WeekParity.even


@dataclass
class DaySchedule:
    day: date
    weekday_name: str
    parity: WeekParity
    lessons: list[Lesson]


async def lessons_for_day(
    session: AsyncSession, on: date, semester_start: date
) -> DaySchedule:
    parity = week_parity(on, semester_start)
    stmt = (
        select(Lesson)
        .options(selectinload(Lesson.subject))
        .where(Lesson.weekday == on.weekday())
        .where(Lesson.week_parity.in_([WeekParity.any, parity]))
        .order_by(Lesson.pair_no, Lesson.starts_at)
    )
    lessons = list(await session.scalars(stmt))
    return DaySchedule(on, WEEKDAY_NAMES[on.weekday()], parity, lessons)


async def lessons_for_week(
    session: AsyncSession, monday: date, semester_start: date
) -> list[DaySchedule]:
    out = []
    for i in range(6):  # Пн–Сб
        out.append(await lessons_for_day(session, monday + timedelta(days=i), semester_start))
    return out


def format_day(day: DaySchedule) -> str:
    from bot import texts

    parity_label = texts.WEEK_ODD if day.parity == WeekParity.odd else texts.WEEK_EVEN
    header = f"<b>{day.weekday_name}</b>, {day.day.strftime('%d.%m')} ({parity_label})"
    if not day.lessons:
        return f"{header}\nПар нет."
    rows = [header]
    for les in day.lessons:
        t = les.starts_at.strftime("%H:%M")
        if les.ends_at:
            t += "–" + les.ends_at.strftime("%H:%M")
        bits = [f"{les.pair_no}. {t}  <b>{les.subject.name}</b>"]
        extra = " · ".join(
            x for x in [les.kind, les.room and f"ауд. {les.room}", les.teacher] if x
        )
        if extra:
            bits.append(f"   {extra}")
        if les.note:
            bits.append(f"   <i>{les.note}</i>")
        rows.append("\n".join(bits))
    return "\n".join(rows)
