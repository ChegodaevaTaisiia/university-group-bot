"""ЧаВо: список для всех + управление старостой."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import FaqEntry, User
from bot.filters import IsAdmin, IsRegistered
from bot.keyboards.menu import cancel_menu, main_menu

router = Router(name="faq")


class AddFaq(StatesGroup):
    question = State()
    answer = State()


@router.message(IsRegistered(), F.text.casefold() == texts.BTN_FAQ.casefold())
@router.message(IsRegistered(), Command("faq"))
async def faq_list(message: Message, session: AsyncSession, user: User):
    entries = (await session.scalars(select(FaqEntry).order_by(FaqEntry.id))).all()
    if not entries:
        text = "ЧаВо пока пустое."
    else:
        lines = ["<b>❓ Частые вопросы</b>", ""]
        for e in entries:
            lines.append(f"<b>{e.question}</b>\n{e.answer}\n")
        text = "\n".join(lines)
    kb = None
    if user.is_admin:
        b = InlineKeyboardBuilder()
        b.button(text="➕ Добавить вопрос", callback_data="faq:add")
        for e in entries:
            b.button(text=f"🗑 {e.question[:35]}", callback_data=f"faq:del:{e.id}")
        b.adjust(1)
        kb = b.as_markup()
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "faq:add", IsAdmin())
async def faq_add(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddFaq.question)
    await cb.message.answer("Вопрос:", reply_markup=cancel_menu())
    await cb.answer()


@router.message(AddFaq.question, F.text)
async def faq_q(message: Message, state: FSMContext):
    await state.update_data(q=message.text.strip())
    await state.set_state(AddFaq.answer)
    await message.answer("Ответ:")


@router.message(AddFaq.answer, F.text)
async def faq_a(message: Message, state: FSMContext, session: AsyncSession, user: User):
    data = await state.get_data()
    session.add(FaqEntry(question=data["q"], answer=message.text.strip(), updated_by=user.id))
    await session.commit()
    await state.clear()
    await message.answer("Добавила в ЧаВо.", reply_markup=main_menu(True))


@router.callback_query(F.data.startswith("faq:del:"), IsAdmin())
async def faq_del(cb: CallbackQuery, session: AsyncSession):
    e = await session.get(FaqEntry, int(cb.data.split(":")[2]))
    if e:
        await session.delete(e)
        await session.commit()
    await cb.answer("Удалила.")
    await cb.message.edit_reply_markup(reply_markup=None)
