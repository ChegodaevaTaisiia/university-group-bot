"""Парсинг человеческого ввода даты/времени на русском.

Понимает:
  • «через 2 часа», «через 30 минут», «через 3 дня»
  • «завтра», «послезавтра», «сегодня» (+ опц. время)
  • «в понедельник», «во вторник» … (ближайший будущий; + опц. время)
  • «15 сентября», «15.09», «15.09.2026» (+ опц. время)
  • «10:00», «9.30» — только время (сегодня или завтра, если уже прошло)

Возвращает timezone-aware datetime в UTC либо None.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}
WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
    "пятниц": 4, "суббот": 5, "воскресень": 6,
}

# Время — только с двоеточием, чтобы не путать с датой «18.09.2026».
_TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")
_REL_RE = re.compile(r"через\s+(\d+)\s*(минут|час|день|дн|недел)", re.IGNORECASE)
_DMY_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")
_DM_TEXT_RE = re.compile(r"\b(\d{1,2})\s+([а-яё]+)", re.IGNORECASE)


def _extract_time(text: str) -> tuple[int, int] | None:
    m = _TIME_RE.search(text)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if 0 <= hh < 24 and 0 <= mm < 60:
        return hh, mm
    return None


def parse_when(text: str, tz: ZoneInfo, *, now: datetime | None = None) -> datetime | None:
    text = text.strip().lower()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    # относительное «через N ...»
    m = _REL_RE.search(text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("минут"):
            delta = timedelta(minutes=n)
        elif unit.startswith("час"):
            delta = timedelta(hours=n)
        elif unit.startswith("недел"):
            delta = timedelta(weeks=n)
        else:
            delta = timedelta(days=n)
        return (now + delta).astimezone(UTC)

    hm = _extract_time(text)

    def at(d: datetime) -> datetime:
        h, mm = hm if hm else (9, 0)
        return d.replace(hour=h, minute=mm, second=0, microsecond=0)

    if "послезавтра" in text:
        return at(now + timedelta(days=2)).astimezone(UTC)
    if "завтра" in text:
        return at(now + timedelta(days=1)).astimezone(UTC)
    if "сегодня" in text:
        return at(now).astimezone(UTC)

    # день недели
    for key, wd in WEEKDAYS.items():
        if key in text:
            ahead = (wd - now.weekday()) % 7
            if ahead == 0:
                ahead = 7
            return at(now + timedelta(days=ahead)).astimezone(UTC)

    # «15 сентября»
    m = _DM_TEXT_RE.search(text)
    if m:
        day = int(m.group(1))
        word = m.group(2)
        for stem, mon in MONTHS.items():
            if word.startswith(stem):
                year = now.year
                cand = now.replace(
                    month=mon, day=min(day, 28) if mon == 2 else day,
                    hour=0, minute=0, second=0, microsecond=0,
                )
                cand = cand.replace(day=day)
                if cand.date() < now.date():
                    cand = cand.replace(year=year + 1)
                return at(cand).astimezone(UTC)

    # «15.09» / «15.09.2026»
    m = _DMY_RE.search(text)
    if m:
        day, mon = int(m.group(1)), int(m.group(2))
        year = m.group(3)
        if year:
            year = int(year)
            if year < 100:
                year += 2000
        else:
            year = now.year
        try:
            cand = now.replace(
                year=year, month=mon, day=day, hour=0, minute=0, second=0, microsecond=0
            )
        except ValueError:
            return None
        if not m.group(3) and cand.date() < now.date():
            cand = cand.replace(year=year + 1)
        return at(cand).astimezone(UTC)

    # только время
    if hm:
        cand = at(now)
        if cand <= now:
            cand += timedelta(days=1)
        return cand.astimezone(UTC)

    return None


def fmt_local(dt: datetime, tz: ZoneInfo) -> str:
    local = dt.astimezone(tz)
    return local.strftime("%d.%m.%Y %H:%M")
