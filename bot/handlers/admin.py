"""Староста: меню управления, рассылки, привязка тем к предметам, список группы, тест ИИ."""

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
from bot.keyboards.menu import admin_menu, cancel_menu, yes_no
from bot.services.ai.client import AiClient
from bot.services.broadcast import broadcast_to_students

router = Router(name="admin")


class Broadcast(StatesGroup):
    content = State()
    confirm = State()


@router.message(F.text.casefold() == texts.BTN_ADMIN.casefold(), IsAdmin())
@router.message(Command("admin"), IsAdmin())
async def admin_root(message: Message):
    await message.answer(texts.ADMIN_MENU, reply_markup=admin_menu())


@router.message(F.text.casefold() == texts.BTN_ADMIN.casefold(), IsRegistered())
async def admin_denied(message: Message):
    await message.answer(texts.NOT_ADMIN)


# ─────────────────────────── рассылка ────────────────────────────────────


@router.callback_query(F.data == "admin:broadcast", IsAdmin())
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
    count = await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
    await state.set_state(Broadcast.confirm)
    await message.answer(
        texts.BROADCAST_CONFIRM.format(count=count), reply_markup=yes_no("bc")
    )


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


# ───────────────────── привязка темы к предмету ──────────────────────────


@router.message(Command("bind_subject"))
async def bind_subject(message: Message, session: AsyncSession, user: User | None):
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


# ───────────────────────── список группы ─────────────────────────────────


@router.callback_query(F.data == "admin:roster", IsAdmin())
async def roster(cb: CallbackQuery, session: AsyncSession):
    users = list(await session.scalars(select(User).order_by(User.full_name)))
    lines = [f"<b>Группа</b> — {len(users)} чел.", ""]
    for u in users:
        tag = " 👑" if u.is_admin else ("" if u.is_active else " (не активен)")
        lines.append(f"• {u.full_name}{tag}")
    await cb.message.answer("\n".join(lines))
    await cb.answer()


# ─────────────────────────── тест ИИ ─────────────────────────────────────


@router.callback_query(F.data == "admin:ai_selftest", IsAdmin())
@router.message(Command("ai_selftest"), IsAdmin())
async def ai_selftest(event: Message | CallbackQuery, session: AsyncSession, ai: AiClient):
    message = event if isinstance(event, Message) else event.message
    if isinstance(event, CallbackQuery):
        await event.answer()
    if not ai.enabled:
        await message.answer(texts.AI_DISABLED)
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
        await message.answer(f"Ошибка ИИ: {e}")
        return
    await message.answer(
        texts.AI_SELFTEST_OK.format(
            model=res.model, inp=res.input_tokens, out=res.output_tokens, cost=res.cost_usd
        )
    )
