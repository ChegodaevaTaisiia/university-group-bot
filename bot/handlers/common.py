"""/start, регистрация по ФИО, главное меню, /cancel, /help, /chatid."""

from __future__ import annotations

import contextlib
import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ErrorEvent, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import get_settings
from bot.db.models import Role, User
from bot.keyboards.menu import main_menu
from bot.utils.names import first_name, normalize_name

router = Router(name="common")
log = logging.getLogger(__name__)


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    log.exception("Ошибка в обработчике: %s", event.exception)
    upd = event.update
    msg = getattr(upd, "message", None) or getattr(getattr(upd, "callback_query", None), "message", None)
    if msg is not None:
        with contextlib.suppress(Exception):
            await msg.answer(texts.SOMETHING_WRONG)
    cb = getattr(upd, "callback_query", None)
    if cb is not None:
        with contextlib.suppress(Exception):
            await cb.answer()
    return True


class Register(StatesGroup):
    waiting_name = State()


def _looks_like_name(text: str) -> bool:
    parts = [p for p in text.strip().split() if p]
    return 2 <= len(parts) <= 4 and all(p[0].isalpha() for p in parts)


async def _is_group_member(message: Message) -> bool:
    settings = get_settings()
    if settings.supergroup_id is None:
        return True  # супергруппа не настроена — не проверяем
    try:
        member = await message.bot.get_chat_member(
            settings.supergroup_id, message.from_user.id
        )
    except Exception as e:  # noqa: BLE001
        log.warning("get_chat_member failed: %s", e)
        return True  # не блокируем из-за технической ошибки
    return member.status in {"creator", "administrator", "member", "restricted"}


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession, user: User | None):
    await state.clear()
    if user is not None:
        await message.answer(
            texts.WELCOME_BACK.format(name=first_name(user.full_name)),
            reply_markup=main_menu(user.is_admin),
        )
        return

    if not await _is_group_member(message):
        await message.answer(texts.NOT_IN_GROUP)
        return

    await message.answer(texts.START_UNKNOWN)
    await state.set_state(Register.waiting_name)


@router.message(Register.waiting_name, F.text)
async def reg_name(message: Message, state: FSMContext, session: AsyncSession):
    name = " ".join(message.text.split())
    if not _looks_like_name(name):
        await message.answer(texts.START_ASK_NAME_AGAIN)
        return

    settings = get_settings()
    is_admin = message.from_user.id in settings.admin_ids
    norm = normalize_name(name)

    # если староста уже завела эту фамилию в списке группы — «занимаем» ту запись
    user = await session.scalar(
        select(User).where(User.tg_id.is_(None), User.full_name_norm == norm)
    )
    if user is not None:
        user.tg_id = message.from_user.id
        user.username = message.from_user.username
        user.full_name = name
        if is_admin:
            user.role = Role.admin
    else:
        user = User(
            tg_id=message.from_user.id,
            username=message.from_user.username,
            full_name=name,
            full_name_norm=norm,
            role=Role.admin if is_admin else Role.student,
        )
        session.add(user)
    await session.commit()
    await state.clear()
    await message.answer(
        texts.REGISTERED.format(name=first_name(name)),
        reply_markup=main_menu(user.is_admin),
    )


@router.message(Command("cancel"))
@router.message(F.text.casefold() == texts.BTN_CANCEL.casefold())
async def cmd_cancel(message: Message, state: FSMContext, user: User | None):
    await state.clear()
    await message.answer(
        texts.CANCELLED, reply_markup=main_menu(bool(user and user.is_admin))
    )


@router.message(Command("help"))
async def cmd_help(message: Message, user: User | None):
    is_admin = bool(user and user.is_admin)
    text = (
        "Пользуйся кнопками меню снизу:\n"
        "📅 Расписание · 📚 Домашка · ⏰ Напоминания · 🤖 Спросить бота · ❓ ЧаВо\n\n"
        "Просто напиши боту вопрос об учёбе — отвечу по тому, что знаю."
    )
    if is_admin:
        text += (
            "\n\n<b>Тебе как старосте:</b>\n"
            "⚙️ Панель старосты — рассылки, расписание, база знаний, настройка.\n"
            "<code>/topic Матанализ</code> — внутри темы супергруппы, привязать её к предмету.\n"
            "<code>/reply N текст</code> — ответить на вопрос студента."
        )
    await message.answer(text, reply_markup=main_menu(is_admin))


@router.message(Command("chatid"))
async def cmd_chatid(message: Message):
    thread = message.message_thread_id
    await message.answer(
        f"chat_id: <code>{message.chat.id}</code>\n"
        f"message_thread_id: <code>{thread}</code>"
    )


@router.message(StateFilter(None), F.chat.type == "private", Command("menu"))
async def cmd_menu(message: Message, user: User | None):
    await message.answer(
        texts.MAIN_MENU, reply_markup=main_menu(bool(user and user.is_admin))
    )
