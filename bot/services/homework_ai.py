"""ИИ-помощь по ДЗ: извлечение задания из текста/фото и сравнение двух формулировок.

Всё опционально: если ИИ выключен, хендлер использует только rapidfuzz.
"""

from __future__ import annotations

import base64
import json
import logging

from pydantic import BaseModel
from rapidfuzz import fuzz
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.ai.client import AiClient
from bot.services.ai.prompts import HOMEWORK_EXTRACT_SYSTEM, HOMEWORK_SAME_SYSTEM

log = logging.getLogger(__name__)

FUZZY_SAME_THRESHOLD = 85


class HomeworkExtract(BaseModel):
    subject_hint: str = ""
    due_hint: str = ""
    task_text: str = ""
    confidence: float = 0.0


class SameCheck(BaseModel):
    same: bool = False
    short_reason: str = ""


def normalize(text: str) -> str:
    import re

    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fuzzy_same(a: str, b: str) -> bool:
    return fuzz.token_set_ratio(normalize(a), normalize(b)) >= FUZZY_SAME_THRESHOLD


async def extract_from_text(
    ai: AiClient, session: AsyncSession, text: str, user_id: int | None
) -> HomeworkExtract:
    res = await ai.complete(
        session=session,
        system=HOMEWORK_EXTRACT_SYSTEM + _JSON_HINT(HomeworkExtract),
        user_content=text,
        kind="homework",
        user_id=user_id,
        max_tokens=400,
        question_for_log=text,
    )
    return _parse(res.text, HomeworkExtract)


async def extract_from_photo(
    ai: AiClient, session: AsyncSession, image_bytes: bytes, media_type: str,
    user_id: int | None, caption: str = "",
) -> HomeworkExtract:
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.standard_b64encode(image_bytes).decode(),
            },
        },
        {"type": "text", "text": caption or "Что за домашнее задание на фото?"},
    ]
    res = await ai.complete(
        session=session,
        system=HOMEWORK_EXTRACT_SYSTEM + _JSON_HINT(HomeworkExtract),
        user_content=content,
        kind="homework",
        user_id=user_id,
        max_tokens=400,
        question_for_log="[photo] " + caption,
    )
    return _parse(res.text, HomeworkExtract)


async def same_assignment(
    ai: AiClient, session: AsyncSession, a: str, b: str
) -> bool:
    if fuzzy_same(a, b):
        return True
    if not ai.enabled:
        return False
    try:
        res = await ai.complete(
            session=session,
            system=HOMEWORK_SAME_SYSTEM + _JSON_HINT(SameCheck),
            user_content=f"A: {a}\n\nB: {b}",
            kind="homework",
            max_tokens=150,
            record=False,
        )
        return _parse(res.text, SameCheck).same
    except Exception:  # noqa: BLE001
        log.exception("same_assignment AI check failed")
        return False


def _JSON_HINT(model: type[BaseModel]) -> str:
    return (
        "\n\nОтветь СТРОГО одним JSON-объектом с полями "
        f"{list(model.model_fields)} и ничем больше."
    )


def _parse(text: str, model: type[BaseModel]) -> BaseModel:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1]
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        return model.model_validate(json.loads(text))
    except Exception:  # noqa: BLE001
        log.warning("failed to parse AI JSON: %s", text[:200])
        return model()
