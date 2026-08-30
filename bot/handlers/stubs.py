"""Разделы следующих этапов: показываем «в разработке», но пункты уже в меню."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from bot import texts
from bot.filters import IsRegistered

router = Router(name="stubs")
router.message.filter(IsRegistered())

_LABELS = {texts.BTN_ATTENDANCE, texts.BTN_DOCS, texts.BTN_DEFENSE}


@router.message(F.text.in_(_LABELS))
async def in_dev(message: Message):
    await message.answer(texts.IN_DEV)
