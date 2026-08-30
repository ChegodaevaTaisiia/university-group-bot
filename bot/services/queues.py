"""Логика тем и очередей на защиту: разбор строк окошек, бронь, напоминания."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import (
    DefenseEvent,
    DefenseSlot,
    Lesson,
    Reminder,
    ReminderRepeat,
    TopicItem,
    TopicList,
)

_SLOT_RE = re.compile(
    r"^\s*(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\s+"
    r"(\d{1,2})(?:\s*пара)?\s*(?:[xх*]\s*(\d{1,2}))?\s*$",
    re.IGNORECASE,
)


def parse_slot_lines(text: str) -> tuple[list[dict], list[str]]:
    """«10.10 3 пара x2» → [{date, pair, count}]. Возвращает (ok, ошибочные строки)."""
    ok: list[dict] = []
    bad: list[str] = []
    today = date.today()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _SLOT_RE.match(line)
        if not m:
            bad.append(line)
            continue
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        pair = int(m.group(4))
        count = int(m.group(5)) if m.group(5) else 1
        try:
            d = date(year, month, day)
        except ValueError:
            bad.append(line)
            continue
        if not m.group(3) and d < today:
            d = d.replace(year=year + 1)
        if not (1 <= pair <= 8) or not (1 <= count <= 30):
            bad.append(line)
            continue
        ok.append({"date": d, "pair": pair, "count": count})
    return ok, bad


async def _pair_time(session: AsyncSession, on: date, pair: int) -> time | None:
    row = await session.scalar(
        select(Lesson.starts_at).where(
            Lesson.weekday == on.weekday(), Lesson.pair_no == pair
        ).limit(1)
    )
    return row


async def create_slots(session: AsyncSession, event: DefenseEvent, parsed: list[dict]) -> int:
    created = 0
    for row in parsed:
        at = await _pair_time(session, row["date"], row["pair"])
        for i in range(row["count"]):
            session.add(
                DefenseSlot(
                    event_id=event.id, on_date=row["date"], pair_no=row["pair"],
                    at_time=at, position=i,
                )
            )
            created += 1
    await session.commit()
    return created


def _pair_label(slot: DefenseSlot) -> str:
    t = f" ({slot.at_time.strftime('%H:%M')})" if slot.at_time else ""
    return f"{slot.on_date.strftime('%d.%m')}, {slot.pair_no} пара{t}"


async def book_slot(session: AsyncSession, slot: DefenseSlot, user_id: int) -> None:
    slot.user_id = user_id
    slot.booked_at = datetime.now(UTC)
    await session.flush()
    await _sync_reminder(session, slot, add=True)
    await session.commit()


async def unbook_slot(session: AsyncSession, slot: DefenseSlot) -> None:
    await _sync_reminder(session, slot, add=False)
    slot.user_id = None
    slot.booked_at = None
    await session.commit()


async def add_reserve(session: AsyncSession, event: DefenseEvent, user_id: int) -> bool:
    exists = await session.scalar(
        select(DefenseSlot).where(
            DefenseSlot.event_id == event.id,
            DefenseSlot.is_reserve.is_(True),
            DefenseSlot.user_id == user_id,
        )
    )
    if exists:
        return False
    session.add(DefenseSlot(event_id=event.id, is_reserve=True, user_id=user_id,
                            booked_at=datetime.now(UTC)))
    await session.commit()
    return True


async def _sync_reminder(session: AsyncSession, slot: DefenseSlot, *, add: bool) -> None:
    """Кладём/убираем напоминание студенту про его окошко (вечер накануне + утро)."""
    settings = get_settings()
    tag = f"defense_slot:{slot.id}"

    everyone = await session.scalars(select(Reminder).where(Reminder.is_active.is_(True)))
    for r in everyone:
        if isinstance(r.payload, dict) and r.payload.get("tag") == tag:
            await session.delete(r)

    if not add or slot.user_id is None or slot.on_date is None:
        return

    event = await session.get(DefenseEvent, slot.event_id)
    title = f"🎓 {event.title if event else 'Защита'} — {_pair_label(slot)}"
    at = slot.at_time or time(9, 0)
    local_dt = datetime.combine(slot.on_date, at, tzinfo=settings.tz)
    fires = {
        (local_dt - timedelta(hours=15)),  # накануне вечером ~18:00 если пара 9:00
        (local_dt - timedelta(hours=2)),
    }
    for f in fires:
        if f > datetime.now(settings.tz):
            session.add(
                Reminder(
                    user_id=slot.user_id,
                    title=title,
                    fire_at=f.astimezone(UTC),
                    repeat=ReminderRepeat.none,
                    payload={"tag": tag},
                )
            )


async def free_topics_count(session: AsyncSession, lst: TopicList) -> tuple[int, int]:
    items = await session.scalars(select(TopicItem).where(TopicItem.list_id == lst.id))
    items = list(items)
    free = sum(1 for i in items if i.taken_by is None)
    return free, len(items)
