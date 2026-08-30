"""Развлечения: 🔮 шар, 🪙 монетка, 🎲 кубик, 🎯 кого спросят, 😎 мем дня.

Работают и в личке (кнопки + команды), и в групповом чате (команды).
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.services.fun import (
    flip_coin,
    magic_ball,
    random_meme,
    roll_dice,
    who_gets_asked,
)

router = Router(name="fun")


def _fun_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔮 Шар", callback_data="fun:ball")
    kb.button(text="🪙 Монетка", callback_data="fun:coin")
    kb.button(text="🎲 Кубик", callback_data="fun:dice")
    kb.button(text="🎯 Кого спросят", callback_data="fun:who")
    kb.button(text="😎 Мем дня", callback_data="fun:meme")
    kb.adjust(2)
    return kb


@router.message(F.text.casefold() == texts.BTN_FUN.casefold())
async def fun_menu(message: Message):
    await message.answer("🎲 <b>Развлечения</b>", reply_markup=_fun_kb().as_markup())


async def _send_meme(message: Message, session: AsyncSession) -> None:
    file_id = await random_meme(session)
    if file_id:
        await message.answer_photo(file_id)
    else:
        await message.answer("Мемы ещё не загружены. Староста — панель → «Картинки».")


@router.message(Command("ball"))
async def cmd_ball(message: Message):
    await message.reply(magic_ball(message.text.partition(" ")[2]))


@router.message(Command("coin"))
async def cmd_coin(message: Message):
    await message.reply(flip_coin())


@router.message(Command("dice"))
async def cmd_dice(message: Message):
    await message.reply(roll_dice())


@router.message(Command("who"))
async def cmd_who(message: Message, session: AsyncSession):
    await message.reply(await who_gets_asked(session))


@router.message(Command("meme"))
async def cmd_meme(message: Message, session: AsyncSession):
    await _send_meme(message, session)


@router.callback_query(F.data.startswith("fun:"))
async def fun_cb(cb: CallbackQuery, session: AsyncSession):
    action = cb.data.split(":", 1)[1]
    if action == "ball":
        await cb.message.answer(magic_ball())
    elif action == "coin":
        await cb.message.answer(flip_coin())
    elif action == "dice":
        await cb.message.answer(roll_dice())
    elif action == "who":
        await cb.message.answer(await who_gets_asked(session))
    elif action == "meme":
        await _send_meme(cb.message, session)
    await cb.answer()
