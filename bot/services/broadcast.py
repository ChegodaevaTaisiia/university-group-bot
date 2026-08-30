"""Массовая отправка в личку студентам с ограничением частоты и отчётом."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import User

log = logging.getLogger(__name__)


async def broadcast_to_students(
    bot: Bot, session: AsyncSession, text: str, *, photo_file_id: str | None = None
) -> tuple[int, int]:
    users = list(
        await session.scalars(select(User).where(User.is_active.is_(True)))
    )
    ok = failed = 0
    for user in users:
        try:
            if photo_file_id:
                await bot.send_photo(user.tg_id, photo_file_id, caption=text)
            else:
                await bot.send_message(user.tg_id, text)
            ok += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            continue
        except TelegramForbiddenError:
            user.is_active = False
            failed += 1
        except Exception as e:  # noqa: BLE001
            log.warning("broadcast to %s failed: %s", user.tg_id, e)
            failed += 1
        await asyncio.sleep(0.05)  # ~20 сообщений/сек
    await session.commit()
    return ok, failed
