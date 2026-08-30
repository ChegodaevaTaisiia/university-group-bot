"""Парсер сайта универа → записи базы знаний (преподаватели / кафедры).

⚠️ Структура сайта пока неизвестна — Таисия даст ссылку позже.
Здесь каркас: список источников в KB_SOURCES, функция парсинга страницы, идемпотентный
upsert по (source_url, title). Селекторы подставим под реальный сайт.
"""

from __future__ import annotations

import logging

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.db.models import KbCategory, KbEntry

log = logging.getLogger(__name__)

# TODO: заполнить после получения ссылки на сайт.
# Каждый источник: (url, category, css-селектор карточки).
KB_SOURCES: list[tuple[str, KbCategory, str]] = []

_HEADERS = {"User-Agent": "Mozilla/5.0 (group-bot KB importer)"}


async def _fetch(url: str) -> str:
    async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def parse_people(html: str, card_selector: str) -> list[dict]:
    """Возвращает список dict(title, body, attrs) — по одной карточке преподавателя."""
    tree = HTMLParser(html)
    out: list[dict] = []
    for card in tree.css(card_selector):
        name = (card.css_first("h3, .name, .fio") or card).text(strip=True)
        if not name:
            continue
        attrs: dict[str, str] = {}
        for row in card.css("li, .field, p"):
            txt = row.text(strip=True)
            if ":" in txt:
                k, v = txt.split(":", 1)
                attrs[k.strip().lower()] = v.strip()
        out.append({"title": name, "body": card.text(strip=True)[:1000], "attrs": attrs})
    return out


async def _upsert(session: AsyncSession, url: str, category: KbCategory, items: list[dict]) -> int:
    n = 0
    for item in items:
        existing = await session.scalar(
            select(KbEntry).where(
                KbEntry.source_url == url, KbEntry.title == item["title"]
            )
        )
        if existing:
            existing.body = item["body"]
            existing.attrs = item["attrs"]
            existing.is_active = True
        else:
            session.add(
                KbEntry(
                    category=category,
                    title=item["title"],
                    body=item["body"],
                    attrs=item["attrs"],
                    source_url=url,
                    source="parsed",
                )
            )
        n += 1
    await session.commit()
    return n


async def refresh_from_site(sessionmaker: async_sessionmaker) -> int:
    if not KB_SOURCES:
        log.info("KB_SOURCES пуст — нечего парсить (ждём ссылку на сайт)")
        return 0
    total = 0
    async with sessionmaker() as session:
        for url, category, selector in KB_SOURCES:
            try:
                html = await _fetch(url)
                items = parse_people(html, selector)
                total += await _upsert(session, url, category, items)
            except Exception:  # noqa: BLE001
                log.exception("kb import failed for %s", url)
    log.info("KB refresh: %s записей", total)
    return total
