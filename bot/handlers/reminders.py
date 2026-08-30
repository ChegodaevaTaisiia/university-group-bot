"""Личные напоминания: создать, посмотреть, удалить. + настройки авто-напоминаний (позже)."""

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
from bot.config import get_settings
from bot.db.models import Reminder, ReminderRepeat, User
from bot.filters import IsRegistered
from bot.keyboards.menu import cancel_menu, main_menu
from bot.services.reminders import LEAD_CHOICES, REPEAT_CHOICES
from bot.utils.dates import fmt_local, parse_when

router = Router(name="reminders")
router.message.filter(IsRegistered())


class NewReminder(StatesGroup):
    text = State()
    when = State()
    lead = State()
    repeat = State()


def _list_kb(reminders: list[Reminder]) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новое напоминание", callback_data="rem:new")
    for r in reminders:
        kb.button(text=f"🗑 {r.title[:30]}", callback_data=f"rem:del:{r.id}")
    kb.adjust(1)
    return kb


@router.message(F.text.casefold() == texts.BTN_REMINDERS.casefold())
@router.message(Command("reminders"))
async def reminders_root(message: Message, session: AsyncSession, user: User):
    rems = list(
        await session.scalars(
            select(Reminder)
            .where(Reminder.user_id == user.id, Reminder.is_active.is_(True))
            .order_by(Reminder.fire_at)
        )
    )
    settings = get_settings()
    if not rems:
        text = texts.REM_LIST_EMPTY
    else:
        lines = ["<b>⏰ Твои напоминания</b>", ""]
        for r in rems:
            rep = "" if r.repeat == ReminderRepeat.none else f" · повтор: {r.repeat.value}"
            lines.append(f"• <b>{r.title}</b>\n  {fmt_local(r.fire_at, settings.tz)}{rep}")
        text = "\n".join(lines)
    await message.answer(text, reply_markup=_list_kb(rems).as_markup())


@router.callback_query(F.data == "rem:new")
async def rem_new(cb: CallbackQuery, state: FSMContext):
    await state.set_state(NewReminder.text)
    await cb.message.answer(texts.REM_ASK_TEXT, reply_markup=cancel_menu())
    await cb.answer()


@router.message(NewReminder.text, F.text)
async def rem_got_text(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(NewReminder.when)
    await message.answer(texts.REM_ASK_WHEN)


@router.message(NewReminder.when, F.text)
async def rem_got_when(message: Message, state: FSMContext):
    settings = get_settings()
    when = parse_when(message.text, settings.tz)
    if when is None:
        await message.answer(texts.REM_WHEN_UNCLEAR)
        return
    await state.update_data(when=when.isoformat())
    kb = InlineKeyboardBuilder()
    for label, minutes in LEAD_CHOICES:
        kb.button(text=label, callback_data=f"rem_lead:{minutes}")
    kb.adjust(2)
    await state.set_state(NewReminder.lead)
    await message.answer(texts.REM_ASK_LEAD, reply_markup=kb.as_markup())


@router.callback_query(NewReminder.lead, F.data.startswith("rem_lead:"))
async def rem_got_lead(cb: CallbackQuery, state: FSMContext):
    await state.update_data(lead=int(cb.data.split(":")[1]))
    kb = InlineKeyboardBuilder()
    for label, rep in REPEAT_CHOICES:
        kb.button(text=label, callback_data=f"rem_rep:{rep.value}")
    kb.adjust(1)
    await state.set_state(NewReminder.repeat)
    await cb.message.edit_text(texts.REM_ASK_REPEAT, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(NewReminder.repeat, F.data.startswith("rem_rep:"))
async def rem_got_repeat(cb: CallbackQuery, state: FSMContext, session: AsyncSession, user: User):
    from datetime import datetime, timedelta

    data = await state.get_data()
    repeat = ReminderRepeat(cb.data.split(":")[1])
    fire_at = datetime.fromisoformat(data["when"]) - timedelta(minutes=data["lead"])
    rem = Reminder(
        user_id=user.id,
        title=data["title"],
        fire_at=fire_at,
        lead_minutes=data["lead"],
        repeat=repeat,
    )
    session.add(rem)
    await session.commit()
    await state.clear()
    settings = get_settings()
    await cb.message.edit_text(
        texts.REM_SAVED.format(title=rem.title, when=fmt_local(fire_at, settings.tz))
    )
    await cb.message.answer(texts.MAIN_MENU, reply_markup=main_menu(user.is_admin))
    await cb.answer()


@router.callback_query(F.data.startswith("rem:del:"))
async def rem_delete(cb: CallbackQuery, session: AsyncSession, user: User):
    rem_id = int(cb.data.split(":")[2])
    rem = await session.get(Reminder, rem_id)
    if rem and rem.user_id == user.id:
        await session.delete(rem)
        await session.commit()
    await cb.answer(texts.REM_DELETED)
    if cb.message:
        rems = list(
            await session.scalars(
                select(Reminder)
                .where(Reminder.user_id == user.id, Reminder.is_active.is_(True))
                .order_by(Reminder.fire_at)
            )
        )
        await cb.message.edit_reply_markup(reply_markup=_list_kb(rems).as_markup())
