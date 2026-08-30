"""ЧаВо без ИИ: список, поиск по ключевым словам, быстрый ответ «есть ли ДЗ»."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import FaqEntry
from bot.filters import IsRegistered

router = Router(name="faq")
router.message.filter(IsRegistered())


@router.message(F.text.casefold() == texts.BTN_FAQ.casefold())
@router.message(Command("faq"))
async def faq_list(message: Message, session: AsyncSession):
    entries = (await session.scalars(select(FaqEntry).order_by(FaqEntry.id))).all()
    if not entries:
        await message.answer("ЧаВо пока пустое. Староста ещё наполняет.")
        return
    lines = ["<b>❓ Частые вопросы</b>", ""]
    for e in entries:
        lines.append(f"<b>{e.question}</b>\n{e.answer}\n")
    await message.answer("\n".join(lines))
