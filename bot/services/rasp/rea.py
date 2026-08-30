"""Загрузка расписания группы с rasp.rea.ru.

Сайт отдаёт расписание не в стартовом HTML, а по XHR — и только если сначала
«прогреть» сессию: GET /?q=<группа> → CheckStatus → PageHeaderCard → ScheduleCard.
Преподаватель приходит отдельным запросом GetDetails по (дата, номер пары).
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, time

import httpx
from selectolax.parser import HTMLParser

log = logging.getLogger(__name__)

_BASE = "https://rasp.rea.ru"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_SLOT_RE = re.compile(
    r"updateTimeslotInfo\(\s*&#39;([\d.]+)&#39;\s*,\s*&#39;(\d+)&#39;\s*\)"
)
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass
class RaspLesson:
    week: int              # 1 = числитель, 2 = знаменатель
    weekday: int           # 0 = понедельник
    pair_no: int
    starts_at: time | None
    ends_at: time | None
    subject: str
    kind: str | None       # Лекция / Практическое занятие / …
    room: str | None
    teacher: str | None
    on_date: str           # DD.MM.YYYY — для запроса деталей


def selection_from_url(url: str) -> str:
    """Из «https://rasp.rea.ru/?q=15.27д-ивт01/24б» → «15.27д-ивт01/24б»."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    if "q" in qs:
        return qs["q"][0]
    return url.strip()


class ReaRaspClient:
    def __init__(self, selection: str) -> None:
        self.selection = selection
        self._ref = f"{_BASE}/?q={urllib.parse.quote(selection)}"

    def _headers(self) -> dict[str, str]:
        return {"Referer": self._ref, "X-Requested-With": "XMLHttpRequest"}

    async def _warm(self, c: httpx.AsyncClient) -> None:
        await c.get(f"{_BASE}/", params={"q": self.selection})
        await c.get(f"{_BASE}/Schedule/CheckStatus", headers=self._headers())
        await c.get(
            f"{_BASE}/Schedule/PageHeaderCard",
            params={"selection": self.selection, "catfilter": "0"},
            headers=self._headers(),
        )

    async def _card(self, c: httpx.AsyncClient, week: int) -> str:
        for attempt in range(3):
            r = await c.get(
                f"{_BASE}/Schedule/ScheduleCard",
                params={"selection": self.selection, "weekNum": str(week), "catfilter": "0"},
                headers=self._headers(),
            )
            if r.status_code == 200 and len(r.text) > 3000:
                return r.text
            await asyncio.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"ScheduleCard week={week} не загрузился")

    async def _teacher(self, c: httpx.AsyncClient, on_date: str, pair: int) -> str | None:
        try:
            r = await c.get(
                f"{_BASE}/Schedule/GetDetails",
                params={"selection": self.selection, "date": on_date, "timeSlot": str(pair)},
                headers=self._headers(),
            )
            if r.status_code != 200:
                return None
            h = HTMLParser(r.text)
            for a in h.css("a"):
                href = a.attributes.get("href", "")
                if href.startswith("?q=") and "school" in (a.html or ""):
                    name = a.text(strip=True)
                    for junk in ("school", "group"):
                        name = name.removeprefix(junk)
                    return name.strip() or None
        except Exception:  # noqa: BLE001
            log.warning("GetDetails failed for %s/%s", on_date, pair)
        return None

    async def fetch(self, *, weeks: tuple[int, ...] = (1, 2), with_teachers: bool = True) -> list[RaspLesson]:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept-Language": "ru-RU,ru;q=0.9"},
            follow_redirects=True,
            timeout=25,
        ) as c:
            await self._warm(c)
            lessons: list[RaspLesson] = []
            for week in weeks:
                html = await self._card(c, week)
                lessons.extend(_parse_card(html, week))
                await asyncio.sleep(0.4)

            if with_teachers:
                for les in lessons:
                    les.teacher = await self._teacher(c, les.on_date, les.pair_no)
                    await asyncio.sleep(0.3)
        return lessons


def _clean_room(raw: str) -> str | None:
    """«3 корпус - 623 , пл. Основная» → «623, 3 корпус»."""
    if not raw:
        return None
    raw = re.sub(r",?\s*пл\.\s*\S+\s*$", "", raw).strip(" ,")
    m = re.match(r"(\d+)\s*корпус\s*-\s*(.+)", raw)
    if m:
        return f"{m.group(2).strip()}, {m.group(1)} корпус"
    return raw or None


def _parse_card(html: str, week: int) -> list[RaspLesson]:
    h = HTMLParser(html)
    out: list[RaspLesson] = []
    for table in h.css("table.table-light"):
        head = table.css_first("th.dayh h5")
        if not head:
            continue
        date_m = re.search(r"(\d{2}\.\d{2}\.\d{4})", head.text())
        if not date_m:
            continue
        on_date = date_m.group(1)
        weekday = datetime.strptime(on_date, "%d.%m.%Y").weekday()

        for row in table.css("tr.slot"):
            task = row.css_first("a.task")
            if task is None:
                continue
            pcap = row.css_first(".pcap")
            if not pcap:
                continue
            pair_no = int(re.search(r"(\d+)", pcap.text()).group(1))
            times = _TIME_RE.findall(row.css_first("td").text())
            starts = time(int(times[0][0]), int(times[0][1])) if len(times) >= 1 else None
            ends = time(int(times[1][0]), int(times[1][1])) if len(times) >= 2 else None

            raw = task.text(separator="\n", strip=True).split("\n")
            subject = raw[0].strip() if raw else "?"
            kind = None
            room_parts: list[str] = []
            it = task.css_first("i")
            if it:
                kind = it.text(strip=True)
            # аудитория: всё после типа занятия
            full = task.text(separator=" ", strip=True)
            after = full.split(kind, 1)[-1] if kind else full
            room = _clean_room(" ".join(after.replace("\n", " ").split()).strip(" ,"))
            _ = room_parts

            out.append(
                RaspLesson(
                    week=week, weekday=weekday, pair_no=pair_no,
                    starts_at=starts, ends_at=ends, subject=subject,
                    kind=kind, room=room, teacher=None, on_date=on_date,
                )
            )
    return out
