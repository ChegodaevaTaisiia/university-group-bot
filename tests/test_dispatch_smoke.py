"""Прогон /start → регистрация → кнопки меню через реальный Dispatcher с мок-ботом.

Цель — убедиться, что связка middleware + роутеры + FSM + БД работает без исключений.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Chat, Message, Update
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.config import get_settings
from bot.db.base import Base
from bot.db.models import User
from bot.handlers import build_router
from bot.middlewares import DbSessionMiddleware, UserMiddleware
from bot.services.ai.client import AiClient


@pytest.fixture(scope="module")
async def env():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware(sm))
    dp.update.middleware(UserMiddleware())
    dp["ai"] = AiClient(get_settings())
    dp.include_router(build_router())

    bot = AsyncMock(spec=Bot)
    bot.id = 42
    bot.get_chat_member.return_value = AsyncMock(status="member")

    yield dp, bot, sm
    await engine.dispose()


def _msg(text: str, uid: int = 555, mid: int = 1) -> Message:
    return Message(
        message_id=mid,
        date=datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=TgUser(id=uid, is_bot=False, first_name="Тест", username="t"),
        text=text,
    )


def _cb(data: str, uid: int, cid: int) -> CallbackQuery:
    holder = Message(
        message_id=900 + cid,
        date=datetime.now(),
        chat=Chat(id=uid, type="private"),
        from_user=TgUser(id=uid, is_bot=True, first_name="bot"),
        text="панель",
    )
    return CallbackQuery(
        id=str(cid),
        from_user=TgUser(id=uid, is_bot=False, first_name="Стар", username="s"),
        chat_instance="ci",
        message=holder,
        data=data,
    )


async def test_start_register_and_menu(env):
    dp, bot, sm = env

    await dp.feed_update(bot, Update(update_id=1, message=_msg("/start")))
    await dp.feed_update(
        bot, Update(update_id=2, message=_msg("Иванова Мария Петровна", mid=2))
    )

    async with sm() as session:
        user = await session.scalar(select(User).where(User.tg_id == 555))
    assert user is not None and user.full_name == "Иванова Мария Петровна"

    # кнопки меню после регистрации — не должны кидать исключений
    for i, label in enumerate(("📅 Расписание", "⏰ Напоминания", "📚 Домашка", "❓ ЧаВо"), start=3):
        await dp.feed_update(bot, Update(update_id=i, message=_msg(label, mid=i)))

    # что-то бот отправлял (send_message или вызов метода) на каждом шаге
    assert len(bot.mock_calls) >= 6


async def test_admin_panel_navigation(env):
    dp, bot, sm = env
    async with sm() as session:  # admin_ids в тестовом окружении = "1"
        session.add(User(tg_id=1, full_name="Староста Тест", username="s", role="admin"))
        await session.commit()

    await dp.feed_update(bot, Update(update_id=40, message=_msg("/panel", uid=1, mid=40)))
    for i, data in enumerate(("p:sched", "p:kb", "p:setup", "p:home"), start=41):
        await dp.feed_update(
            bot, Update(update_id=i, callback_query=_cb(data, uid=1, cid=i))
        )
    # навигация по панели не должна кидать исключений (иначе feed_update пробросит)
    assert bot.mock_calls
