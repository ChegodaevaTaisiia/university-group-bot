"""Рофловые фичи: магический шар, монетка, кубик, «кого спросят», мем дня."""

from __future__ import annotations

import random
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import MediaItem, User

BALL_ANSWERS = [
    "Бесспорно, да.",
    "Даже не сомневайся.",
    "Скорее да, чем нет.",
    "Знаки говорят — да.",
    "Хорошие новости: да.",
    "Пока неясно, спроси позже.",
    "Сконцентрируйся и спроси ещё раз.",
    "Лучше тебе этого не знать.",
    "Не сейчас.",
    "Мои источники говорят — нет.",
    "Очень сомнительно.",
    "Даже не мечтай.",
    "Готовься к пересдаче.",
    "Спроси у старосты, я пас.",
    "50 на 50, как обычно.",
]

COIN = ["🪙 Орёл", "🪙 Решка"]


def magic_ball(_question: str = "") -> str:
    return "🔮 " + random.choice(BALL_ANSWERS)


def flip_coin() -> str:
    return random.choice(COIN)


def roll_dice() -> str:
    return f"🎲 Выпало: {random.randint(1, 6)}"


async def who_gets_asked(session: AsyncSession, *, on: date | None = None) -> str:
    users = list(
        await session.scalars(
            select(User).where(User.is_active.is_(True)).order_by(User.id)
        )
    )
    if not users:
        return "В группе пока никого нет."
    on = on or date.today()
    rnd = random.Random(on.toordinal())  # стабильно в течение дня
    picked = rnd.choice(users)
    return f"🎯 Сегодня спросят: <b>{picked.full_name}</b> 🫵"


async def random_meme(session: AsyncSession) -> str | None:
    file_id = await session.scalar(
        select(MediaItem.file_id)
        .where(MediaItem.kind == "meme")
        .order_by(func.random())
        .limit(1)
    )
    return file_id
