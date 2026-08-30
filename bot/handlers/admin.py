"""Панель старосты: навигация по разделам + рассылки, список группы, привязка тем, тест ИИ."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import Subject, User
from bot.filters import IsAdmin, IsRegistered
from bot.keyboards.menu import (
    cancel_menu,
    panel_home,
    panel_kb,
    panel_sched,
    panel_setup,
    yes_no,
)
from bot.services.ai.client import AiClient
from bot.services.broadcast import broadcast_to_students
from bot.services.seed import seed_demo, wipe_demo

router = Router(name="admin")


class Broadcast(StatesGroup):
    content = State()
    confirm = State()


# ─────────────────────────── вход в панель ───────────────────────────────


@router.message(F.text.casefold() == texts.BTN_ADMIN.casefold(), IsAdmin())
@router.message(Command("panel"), IsAdmin())
async def panel_open(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(texts.PANEL_TITLE, reply_markup=panel_home())


@router.message(F.text.casefold() == texts.BTN_ADMIN.casefold(), IsRegistered())
async def admin_denied(message: Message):
    await message.answer(texts.NOT_ADMIN)


# ─────────────────────── навигация по разделам ──────────────────────────


@router.callback_query(F.data == "p:home", IsAdmin())
async def nav_home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(texts.PANEL_TITLE, reply_markup=panel_home())
    await cb.answer()


@router.callback_query(F.data == "p:sched", IsAdmin())
async def nav_sched(cb: CallbackQuery):
    await cb.message.edit_text(texts.PANEL_SCHED_TITLE, reply_markup=panel_sched())
    await cb.answer()


@router.callback_query(F.data == "p:kb", IsAdmin())
async def nav_kb(cb: CallbackQuery):
    await cb.message.edit_text(texts.PANEL_KB_TITLE, reply_markup=panel_kb())
    await cb.answer()


@router.callback_query(F.data == "p:setup", IsAdmin())
async def nav_setup(cb: CallbackQuery):
    await cb.message.edit_text(texts.PANEL_SETUP_TITLE, reply_markup=panel_setup())
    await cb.answer()


@router.callback_query(F.data == "p:topic_help", IsAdmin())
async def nav_topic_help(cb: CallbackQuery):
    await cb.message.answer(texts.TOPIC_HELP)
    await cb.answer()


# ─────────────────────────── рассылка ────────────────────────────────────


@router.callback_query(F.data == "p:broadcast", IsAdmin())
async def bc_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Broadcast.content)
    await cb.message.answer(texts.BROADCAST_ASK_TEXT, reply_markup=cancel_menu())
    await cb.answer()


@router.message(Broadcast.content, F.photo)
async def bc_photo(message: Message, state: FSMContext, session: AsyncSession):
    await state.update_data(text=message.caption or "", photo=message.photo[-1].file_id)
    await _bc_preview(message, state, session)


@router.message(Broadcast.content, F.text)
async def bc_text(message: Message, state: FSMContext, session: AsyncSession):
    await state.update_data(text=message.text, photo=None)
    await _bc_preview(message, state, session)


async def _bc_preview(message: Message, state: FSMContext, session: AsyncSession):
    count = await session.scalar(
        select(func.count()).select_from(User).where(User.is_active.is_(True))
    )
    await state.set_state(Broadcast.confirm)
    await message.answer(texts.BROADCAST_CONFIRM.format(count=count), reply_markup=yes_no("bc"))


@router.callback_query(Broadcast.confirm, F.data == "bc:no")
async def bc_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(texts.CANCELLED)
    await cb.answer()


@router.callback_query(Broadcast.confirm, F.data == "bc:yes")
async def bc_send(cb: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await cb.message.edit_text("Рассылаю…")
    ok, failed = await broadcast_to_students(
        bot, session, data["text"], photo_file_id=data.get("photo")
    )
    await cb.message.answer(texts.BROADCAST_DONE.format(ok=ok, failed=failed))
    await cb.answer()


# ───────────────────── привязка темы к предмету ─────────────────────────


@router.message(Command("topic"))
async def bind_topic(message: Message, session: AsyncSession, user: User | None):
    if not user or not user.is_admin:
        return
    if message.message_thread_id is None:
        await message.answer(texts.BIND_SUBJECT_NO_TOPIC)
        return
    name = message.text.partition(" ")[2].strip()
    if not name:
        await message.answer(texts.BIND_SUBJECT_USAGE)
        return
    subject = await session.scalar(select(Subject).where(Subject.name.ilike(name)))
    if subject is None:
        subject = Subject(name=name)
        session.add(subject)
    subject.thread_id = message.message_thread_id
    await session.commit()
    await message.answer(texts.BIND_SUBJECT_OK.format(subject=subject.name))


# ─────────────────────── настройка: демо / ИИ ──────────────────────────


@router.callback_query(F.data == "p:seed", IsAdmin())
async def do_seed(cb: CallbackQuery, session: AsyncSession):
    await cb.message.answer(await seed_demo(session))
    await cb.answer()


@router.callback_query(F.data == "p:wipe", IsAdmin())
async def do_wipe(cb: CallbackQuery, session: AsyncSession):
    await cb.message.answer(await wipe_demo(session))
    await cb.answer()


@router.callback_query(F.data == "p:ai_test", IsAdmin())
async def ai_selftest(cb: CallbackQuery, session: AsyncSession, ai: AiClient):
    await cb.answer()
    if not ai.enabled:
        await cb.message.answer(texts.AI_DISABLED)
        return
    try:
        res = await ai.complete(
            session=session,
            system="Ответь одним словом: OK",
            user_content="Проверка связи.",
            kind="selftest",
            max_tokens=20,
        )
    except Exception as e:  # noqa: BLE001
        await cb.message.answer(f"Ошибка ИИ: {e}")
        return
    await cb.message.answer(
        texts.AI_SELFTEST_OK.format(
            model=res.model, inp=res.input_tokens, out=res.output_tokens, cost=res.cost_usd
        )
    )
