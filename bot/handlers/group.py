"""Раздел «Группа»: список участников по алфавиту + свои дни рождения."""

from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import User
from bot.filters import IsRegistered
from bot.keyboards.menu import cancel_menu, main_menu
from bot.services.greetings import parse_birthday

router = Router(name="group")
router.message.filter(IsRegistered())

_MONTHS_GEN = [
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


class SetBirthday(StatesGroup):
    waiting = State()


def _days_until(day: int, month: int, today: date) -> int:
    try:
        this = date(today.year, month, min(day, 28) if month == 2 else day)
    except ValueError:
        this = date(today.year, month, 28)
    if this < today:
        this = this.replace(year=today.year + 1)
    return (this - today).days


async def _roster_text(session: AsyncSession) -> str:
    users = list(
        await session.scalars(
            select(User).where(User.is_active.is_(True)).order_by(User.full_name)
        )
    )
    lines = [f"<b>👥 Группа</b> — {len(users)} чел.", ""]
    for i, u in enumerate(users, 1):
        crown = " 👑" if u.is_admin else ""
        lines.append(f"{i}. {u.full_name}{crown}")
    return "\n".join(lines)


async def _birthdays_text(session: AsyncSession) -> str:
    today = date.today()
    users = list(
        await session.scalars(
            select(User).where(
                User.is_active.is_(True), User.birthday_day.is_not(None)
            )
        )
    )
    if not users:
        return "Никто ещё не указал день рождения."
    users.sort(key=lambda u: _days_until(u.birthday_day, u.birthday_month, today))
    lines = ["<b>🎂 Дни рождения</b>", ""]
    for u in users:
        d = _days_until(u.birthday_day, u.birthday_month, today)
        when = f"{u.birthday_day} {_MONTHS_GEN[u.birthday_month]}"
        if d == 0:
            lines.append(f"🎉 <b>{u.full_name}</b> — сегодня!")
        elif d == 1:
            lines.append(f"• {u.full_name} — завтра ({when})")
        else:
            lines.append(f"• {u.full_name} — {when} (через {d} дн.)")
    return "\n".join(lines)


def _group_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎂 Дни рождения", callback_data="grp:bdays")
    kb.button(text="📝 Указать свой день рождения", callback_data="grp:set_bday")
    kb.adjust(1)
    return kb


@router.message(F.text.casefold() == texts.BTN_GROUP.casefold())
@router.message(Command("group"))
async def group_root(message: Message, session: AsyncSession):
    await message.answer(await _roster_text(session), reply_markup=_group_kb().as_markup())


@router.callback_query(F.data == "grp:bdays")
async def show_bdays(cb: CallbackQuery, session: AsyncSession):
    await cb.message.answer(await _birthdays_text(session))
    await cb.answer()


@router.callback_query(F.data == "grp:set_bday")
async def set_bday_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SetBirthday.waiting)
    await cb.message.answer(
        "Напиши свой день рождения: <code>ДД.ММ</code> или <code>ДД.ММ.ГГГГ</code>\n"
        "(год можно не указывать)",
        reply_markup=cancel_menu(),
    )
    await cb.answer()


@router.message(SetBirthday.waiting, F.text)
async def set_bday_save(message: Message, state: FSMContext, session: AsyncSession, user: User):
    parsed = parse_birthday(message.text)
    if not parsed:
        await message.answer("Не поняла дату. Формат: <code>15.09</code> или <code>15.09.2005</code>")
        return
    day, month, year = parsed
    user.birthday_day, user.birthday_month, user.birthday_year = day, month, year
    await session.commit()
    await state.clear()
    when = f"{day} {_MONTHS_GEN[month]}" + (f" {year}" if year else "")
    await message.answer(f"Запомнила: {when}. Поздравлю группу в этот день 🎂",
                         reply_markup=main_menu(user.is_admin))
