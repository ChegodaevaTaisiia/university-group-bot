"""Общие фильтры aiogram."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message

from bot.db.models import User


class IsRegistered(BaseFilter):
    async def __call__(self, _: Message, user: User | None = None) -> bool:
        return user is not None and user.is_active


class IsAdmin(BaseFilter):
    async def __call__(self, _: Message, user: User | None = None) -> bool:
        return user is not None and user.is_admin
