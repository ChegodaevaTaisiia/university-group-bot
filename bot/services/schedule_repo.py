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
    if on < semester_start:
        # до начала семестра пар нет, даже если чётность формально совпала
        return DaySchedule(on, WEEKDAY_NAMES[on.weekday()], parity, [])
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


_KIND_ICON = {
    "лекция": "📗",
    "практическое занятие": "✏️",
    "практика": "✏️",
    "лабораторная работа": "🧪",
    "лабораторное занятие": "🧪",
    "семинар": "💬",
}
_MONTHS_SHORT = ["", "янв", "фев", "мар", "апр", "мая", "июн",
                 "июл", "авг", "сен", "окт", "ноя", "дек"]


def _kind_icon(kind: str | None) -> str:
    if not kind:
        return "📘"
    return _KIND_ICON.get(kind.strip().lower(), "📘")


def format_day(day: DaySchedule, *, with_header: bool = True) -> str:
    from bot import texts

    parity = texts.WEEK_ODD if day.parity == WeekParity.odd else texts.WEEK_EVEN
    header = (
        f"<b>{day.weekday_name}</b>, {day.day.day} {_MONTHS_SHORT[day.day.month]} · {parity}"
    )
    if not day.lessons:
        body = "  🎉 пар нет"
        return f"{header}\n{body}" if with_header else body

    chunks: list[str] = []
    for les in day.lessons:
        t = les.starts_at.strftime("%H:%M") if les.starts_at else "—"
        if les.ends_at:
            t += "–" + les.ends_at.strftime("%H:%M")
        lines = [
            f"🕐 <b>{t}</b>   <i>{les.pair_no} пара</i>",
            f"{_kind_icon(les.kind)} <b>{les.subject.name}</b>"
            + (f"  ·  {les.kind.lower()}" if les.kind else ""),
        ]
        meta = "   ".join(
            x for x in [
                les.room and f"📍 {les.room}",
                les.teacher and f"👤 {les.teacher}",
            ] if x
        )
        if meta:
            lines.append(meta)
        if les.note:
            lines.append(f"❗ <i>{les.note}</i>")
        chunks.append("\n".join(lines))

    body = "\n\n".join(chunks)
    return f"{header}\n\n{body}" if with_header else body


_DIVIDER = "\n\n━━━━━━━━━━━━━━━\n\n"


def format_week(days: list[DaySchedule], *, title: str | None = None) -> str:
    parts = [format_day(d) for d in days]
    text = _DIVIDER.join(parts)
    if title:
        text = f"<b>{title}</b>{_DIVIDER}{text}"
    return text
