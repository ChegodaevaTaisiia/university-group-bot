"""Парсер сайта РЭУ им. Плеханова → база знаний (преподаватели, контакты дирекции).

Структура сайта (проверено на ВШ кибертехнологий, математики и статистики):
- страница школы:  .../structure/hs/<school>            → блок «Контакты» дирекции
- .../subordinateunits                                  → ссылки на кафедры
- .../subordinateunits/kafedra-*/sotrudniki             → карточки преподавателей
    .inner-page-teachers-item-descr-bg
        .inner-page-teachers-name > a[href="/~person/HASH"]   → ФИО + ссылка
        .inner-page-teachers-text                             → должность/степень
- /~person/HASH   → разделы «Образование», «Преподавательская деятельность»,
                    «Контактная информация» (телефон, кабинет, почта, часы приёма)

Лёгкий проход (5 запросов) тянет всех преподавателей школы: ФИО + должность + кафедра.
Обогащение персональной страницей (почта, кабинет, часы, предметы) — по команде
`/kb_enrich <фамилия>`, чтобы не дёргать сотни страниц и не раздувать базу.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

import httpx
from pydantic import BaseModel
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.config import get_settings
from bot.db.models import KbCategory, KbEntry

log = logging.getLogger(__name__)

_BASE = "https://www.rea.ru"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
_PERSON_SECTIONS = {
    "Преподавательская деятельность",
    "Контактная информация",
    "Образование",
}


async def _get(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url)
        r.raise_for_status()
        return r.text
    except Exception as e:  # noqa: BLE001
        log.warning("KB fetch failed %s: %s", url, e)
        return None


def _abs(href: str) -> str:
    return href if href.startswith("http") else _BASE + href


# ─────────────────────────── парсинг страниц ─────────────────────────────


def discover_staff_urls(units_html: str) -> list[tuple[str, str]]:
    """Со страницы «Подчинённые подразделения» → [(url страницы сотрудников, имя кафедры)]."""
    h = HTMLParser(units_html)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in h.css("a[href]"):
        href = a.attrs.get("href", "").split("#")[0]
        name = a.text(strip=True)
        if "/subordinateunits/kafedra-" in href and href not in seen and name:
            seen.add(href)
            out.append((_abs(href.rstrip("/") + "/sotrudniki"), name))
    return out


def parse_school_contacts(school_html: str, source_url: str) -> dict | None:
    h = HTMLParser(school_html)
    for head in h.css("h1, h2, h3"):
        if head.text(strip=True) == "Контакты" and head.parent:
            body = re.sub(r"\s*\|\s*", "\n", head.parent.text(separator=" | ", strip=True))
            body = re.sub(r"\n{2,}", "\n", body).strip()
            if len(body) > 40:
                return {
                    "title": "Дирекция факультета — контакты",
                    "body": body[:1500],
                    "attrs": {},
                    "source_url": source_url,
                }
    return None


def parse_staff_page(html: str, kafedra: str) -> list[dict]:
    h = HTMLParser(html)
    h1 = h.css_first("h1")
    if h1 and h1.text(strip=True).startswith("Кафедра"):
        kafedra = h1.text(strip=True)
    out: list[dict] = []
    for card in h.css(".inner-page-teachers-item-descr-bg"):
        name_el = card.css_first(".inner-page-teachers-name a")
        if not name_el:
            continue
        name = name_el.text(strip=True)
        pos = card.css_first(".inner-page-teachers-text")
        position = re.sub(r'["\s]+', " ", pos.text(strip=True)).strip() if pos else ""
        person_url = _abs(name_el.attrs.get("href", "")) if name_el.attrs.get("href") else None
        if name:
            out.append(
                {"name": name, "position": position, "kafedra": kafedra, "person_url": person_url}
            )
    return out


def extract_person_sections(html: str) -> str:
    h = HTMLParser(html)
    chunks: list[str] = []
    for head in h.css("h1, h2, h3"):
        title = head.text(strip=True)
        if title in _PERSON_SECTIONS and head.parent:
            txt = re.sub(r"\s*\|\s*", " ", head.parent.text(separator=" | ", strip=True))
            chunks.append(f"### {title}\n{txt}")
    return "\n\n".join(chunks)[:3500]


# ─────────────────────────── обогащение через ИИ ─────────────────────────


class PersonInfo(BaseModel):
    degree: str = ""          # учёная степень/звание
    email: str = ""
    phone: str = ""
    room: str = ""            # кабинет/адрес
    office_hours: str = ""    # часы приёма
    courses: list[str] = []   # предметы, которые ведёт


async def _ai_parse_person(ai, session: AsyncSession, name: str, sections_text: str) -> PersonInfo:
    system = (
        "Ты извлекаешь факты о преподавателе из текста с сайта вуза. "
        "Верни СТРОГО один JSON-объект с полями: "
        f"{list(PersonInfo.model_fields)}. "
        "courses — список названий дисциплин. Если чего-то нет — пустая строка/список. "
        "Ничего не выдумывай."
    )
    res = await ai.complete(
        session=session,
        system=system,
        user_content=f"Преподаватель: {name}\n\n{sections_text}",
        kind="kb_enrich",
        max_tokens=500,
        record=True,
    )
    text = res.text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    s, e = text.find("{"), text.rfind("}")
    try:
        return PersonInfo.model_validate(json.loads(text[s : e + 1]))
    except Exception:  # noqa: BLE001
        log.warning("person JSON parse failed for %s: %s", name, text[:200])
        return PersonInfo()


def _render_person_body(position: str, kafedra: str, info: PersonInfo) -> str:
    lines = [position or info.degree, kafedra]
    if info.courses:
        lines.append("Ведёт: " + ", ".join(info.courses))
    if info.room:
        lines.append("Кабинет/адрес: " + info.room)
    if info.office_hours:
        lines.append("Часы приёма: " + info.office_hours)
    if info.email:
        lines.append("Почта: " + info.email)
    if info.phone:
        lines.append("Телефон: " + info.phone)
    return "\n".join(x for x in lines if x)


# ─────────────────────────────── публичное API ──────────────────────────


async def _upsert_teacher(session: AsyncSession, t: dict, body: str) -> None:
    existing = await session.scalar(
        select(KbEntry).where(KbEntry.title == t["name"], KbEntry.category == KbCategory.teacher)
    )
    attrs = {"кафедра": t["kafedra"], "должность": t["position"]}
    if t.get("person_url"):
        attrs["страница"] = t["person_url"]
    if existing:
        existing.body = body
        existing.attrs = attrs
        existing.source_url = t.get("person_url") or existing.source_url
        existing.is_active = True
    else:
        session.add(
            KbEntry(
                category=KbCategory.teacher,
                title=t["name"],
                body=body,
                attrs=attrs,
                source_url=t.get("person_url"),
                source="parsed",
            )
        )


async def refresh_from_site(sessionmaker: async_sessionmaker) -> int:
    """Лёгкий проход: контакты дирекции + все преподаватели школы (без персон. страниц)."""
    settings = get_settings()
    school_url = settings.kb_school_url
    if not school_url:
        log.info("KB_SCHOOL_URL не задан — пропускаю парсинг")
        return 0

    total = 0
    async with httpx.AsyncClient(headers=_HEADERS, timeout=25, follow_redirects=True) as client:
        school_html = await _get(client, school_url)
        if not school_html:
            return 0

        async with sessionmaker() as session:
            contacts = parse_school_contacts(school_html, school_url)
            if contacts:
                ex = await session.scalar(
                    select(KbEntry).where(KbEntry.title == contacts["title"])
                )
                if ex:
                    ex.body, ex.is_active = contacts["body"], True
                else:
                    session.add(
                        KbEntry(
                            category=KbCategory.department,
                            title=contacts["title"],
                            body=contacts["body"],
                            source_url=school_url,
                            source="parsed",
                        )
                    )
                total += 1

            units_html = await _get(client, school_url.rstrip("/") + "/subordinateunits")
            for su, kafedra in discover_staff_urls(units_html or school_html):
                html = await _get(client, su)
                if not html:
                    continue
                for t in parse_staff_page(html, kafedra):
                    await _upsert_teacher(session, t, f"{t['position']}\n{t['kafedra']}".strip())
                    total += 1
                await asyncio.sleep(0.3)
            await session.commit()

    log.info("KB refresh: %s записей", total)
    return total


async def enrich_teacher(sessionmaker: async_sessionmaker, ai, query: str) -> str:
    """Обогащает карточки преподавателей по фамилии/части ФИО данными с их страницы."""
    if not ai or not ai.enabled:
        return "ИИ выключен — обогащение недоступно."

    async with sessionmaker() as session:
        rows = list(
            await session.scalars(
                select(KbEntry).where(
                    KbEntry.category == KbCategory.teacher,
                    KbEntry.title.ilike(f"%{query.strip()}%"),
                )
            )
        )
        if not rows:
            return f"Не нашла преподавателей по запросу «{query}»."
        if len(rows) > 6:
            return f"Слишком много совпадений ({len(rows)}) — уточни фамилию."

        done: list[str] = []
        async with httpx.AsyncClient(
            headers=_HEADERS, timeout=25, follow_redirects=True
        ) as client:
            for entry in rows:
                url = entry.attrs.get("страница") or entry.source_url
                if not url:
                    continue
                html = await _get(client, url)
                if not html:
                    continue
                sections = extract_person_sections(html)
                if not sections:
                    continue
                info = await _ai_parse_person(ai, session, entry.title, sections)
                entry.body = _render_person_body(
                    entry.attrs.get("должность", ""), entry.attrs.get("кафедра", ""), info
                )
                if info.email:
                    entry.attrs = {**entry.attrs, "почта": info.email}
                done.append(entry.title)
        await session.commit()

    return "Обновила: " + ", ".join(done) if done else "Не удалось обогатить карточки."
