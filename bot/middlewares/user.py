"""Загружает User из БД по tg_id и кладёт в data['user'] (или None, если не зареган)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.db.models import Role, User


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user: TgUser | None = data.get("event_from_user")
        session: AsyncSession | None = data.get("session")
        user: User | None = None

        if tg_user is not None and session is not None and not tg_user.is_bot:
            user = await session.scalar(select(User).where(User.tg_id == tg_user.id))
            if user is not None:
                # Держим username и роль админа в актуальном состоянии.
                changed = False
                if user.username != tg_user.username:
                    user.username = tg_user.username
                    changed = True
                if tg_user.id in get_settings().admin_ids and user.role != Role.admin:
                    user.role = Role.admin
                    changed = True
                if changed:
                    await session.commit()

        data["user"] = user
        return await handler(event, data)
