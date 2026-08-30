"""Подбор записей базы знаний под вопрос. v1 — без эмбеддингов.

Для группы это десятки–сотни коротких записей: делаем грубый лексический отбор,
а если записей мало — просто отдаём все. Итог кладётся в промпт ассистента.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import KbEntry

# Модель Haiku дешёвая и с большим контекстом — при типичной базе (~250 коротких
# записей ≈ 8k токенов) отдаём ВСЮ базу целиком, без отбора. Фильтр включается
# только если база разрастётся за этот порог.
_MAX_ENTRIES = 500
_STOP = set("и в на по о об от до за что как кто это для с у не ли а бы же".split())


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[а-яёa-z0-9]+", text.lower()) if w not in _STOP and len(w) > 2}


def _fuzzy_hits(q: set[str], hay: set[str]) -> int:
    """Совпадения + частичные (китовой↔китова, нефедова↔нефедов)."""
    hits = len(q & hay)
    for a in q - hay:
        if any(a.startswith(b[:5]) or b.startswith(a[:5]) for b in hay if len(b) > 4):
            hits += 1
    return hits


async def relevant_entries(session: AsyncSession, question: str) -> list[KbEntry]:
    entries = list(
        await session.scalars(select(KbEntry).where(KbEntry.is_active.is_(True)))
    )
    if len(entries) <= _MAX_ENTRIES:
        return entries

    q = _tokens(question)
    scored = []
    for e in entries:
        hay = _tokens(f"{e.title} {e.body} {' '.join(str(v) for v in e.attrs.values())}")
        scored.append((_fuzzy_hits(q, hay), e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for score, e in scored[:_MAX_ENTRIES] if score > 0] or entries[:_MAX_ENTRIES]


def render_kb_block(entries: list[KbEntry]) -> str:
    if not entries:
        return "БАЗА ЗНАНИЙ: (пусто)"
    lines = ["БАЗА ЗНАНИЙ:"]
    for e in entries:
        attrs = "; ".join(f"{k}: {v}" for k, v in e.attrs.items() if v)
        block = f"- [{e.title}] {e.body}".strip()
        if attrs:
            block += f" ({attrs})"
        lines.append(block)
    return "\n".join(lines)
