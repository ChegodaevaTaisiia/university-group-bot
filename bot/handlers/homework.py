"""Домашка: просмотр, добавление (текст/фото), консенсус-подтверждение и публикация в тему."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import get_settings
from bot.db.models import Homework, HomeworkStatus, Subject, User
from bot.filters import IsAdmin, IsRegistered
from bot.keyboards.menu import main_menu
from bot.services import homework_ai
from bot.services.ai.client import AiClient
from bot.utils.dates import parse_when

router = Router(name="homework")
router.message.filter(IsRegistered())
log = logging.getLogger(__name__)


class AddHw(StatesGroup):
    subject = State()
    due = State()
    body = State()
    confirm = State()


async def _subjects(session: AsyncSession) -> list[Subject]:
    return list(
        await session.scalars(
            select(Subject).where(Subject.is_active.is_(True)).order_by(Subject.name)
        )
    )


@router.message(F.text.casefold() == texts.BTN_HOMEWORK.casefold())
@router.message(Command("homework"))
async def hw_root(message: Message, session: AsyncSession):
    subjects = await _subjects(session)
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить задание", callback_data="hw:add")
    kb.button(text="🗓 На неделю", callback_data="hw:week")
    for s in subjects:
        kb.button(text=s.name, callback_data=f"hw:subj:{s.id}")
    kb.adjust(2)
    await message.answer(texts.HW_LIST_HEADER, reply_markup=kb.as_markup())


def _fmt_hw_list(items: list[Homework]) -> str:
    if not items:
        return texts.HW_NONE_FOR_SUBJECT
    lines = []
    for hw in items:
        mark = "✅" if hw.status == HomeworkStatus.confirmed else "⏳"
        lines.append(
            f"{mark} <b>{hw.subject.name}</b> — к {hw.due_date.strftime('%d.%m')}\n{hw.text}"
        )
    return "\n\n".join(lines)


@router.callback_query(F.data == "hw:week")
async def hw_week(cb: CallbackQuery, session: AsyncSession):
    today = date.today()
    items = list(
        await session.scalars(
            select(Homework)
            .where(Homework.due_date >= today, Homework.due_date <= today + timedelta(days=8))
            .order_by(Homework.due_date)
        )
    )
    await cb.message.answer(_fmt_hw_list(items))
    await cb.answer()


@router.callback_query(F.data.startswith("hw:subj:"))
async def hw_by_subject(cb: CallbackQuery, session: AsyncSession):
    sid = int(cb.data.split(":")[2])
    items = list(
        await session.scalars(
            select(Homework)
            .where(Homework.subject_id == sid, Homework.due_date >= date.today() - timedelta(days=1))
            .order_by(Homework.due_date)
        )
    )
    await cb.message.answer(_fmt_hw_list(items))
    await cb.answer()


# ─────────────────────────── добавление ──────────────────────────────────


@router.callback_query(F.data == "hw:add")
async def hw_add_start(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    subjects = await _subjects(session)
    if not subjects:
        await cb.answer("Сначала староста добавит предметы (через расписание).", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for s in subjects:
        kb.button(text=s.name, callback_data=f"hw_subj:{s.id}")
    kb.adjust(2)
    await state.set_state(AddHw.subject)
    await cb.message.answer(texts.HW_PICK_SUBJECT, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(AddHw.subject, F.data.startswith("hw_subj:"))
async def hw_add_subject(cb: CallbackQuery, state: FSMContext):
    await state.update_data(subject_id=int(cb.data.split(":")[1]))
    await state.set_state(AddHw.due)
    await cb.message.answer(texts.HW_ASK_DUE)
    await cb.answer()


@router.message(AddHw.due, F.text)
async def hw_add_due(message: Message, state: FSMContext):
    settings = get_settings()
    when = parse_when(message.text, settings.tz)
    if when is None:
        await message.answer(texts.REM_WHEN_UNCLEAR)
        return
    await state.update_data(due=when.date().isoformat())
    await state.set_state(AddHw.body)
    await message.answer(texts.HW_ASK_TEXT)


@router.message(AddHw.body, F.photo)
async def hw_add_photo(message: Message, state: FSMContext, session: AsyncSession, ai: AiClient, user: User):
    file_id = message.photo[-1].file_id
    task_text = message.caption or ""
    if ai.enabled:
        try:
            file = await message.bot.get_file(file_id)
            buf = await message.bot.download_file(file.file_path)
            extract = await homework_ai.extract_from_photo(
                ai, session, buf.read(), "image/jpeg", user.id, message.caption or ""
            )
            if extract.task_text:
                task_text = extract.task_text
        except Exception:  # noqa: BLE001
            log.exception("photo homework extract failed")
    await state.update_data(text=task_text or "(задание на фото)", attachment=file_id)
    await _hw_confirm(message, state)


@router.message(AddHw.body, F.text)
async def hw_add_text(message: Message, state: FSMContext, session: AsyncSession, ai: AiClient, user: User):
    task_text = message.text.strip()
    if ai.enabled and len(task_text) > 15:
        try:
            extract = await homework_ai.extract_from_text(ai, session, task_text, user.id)
            if extract.task_text and extract.confidence >= 0.4:
                task_text = extract.task_text
        except Exception:  # noqa: BLE001
            log.exception("text homework extract failed")
    await state.update_data(text=task_text, attachment=None)
    await _hw_confirm(message, state)


async def _hw_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    from bot.keyboards.menu import yes_no

    await state.set_state(AddHw.confirm)
    await message.answer(
        texts.HW_AI_UNDERSTOOD.format(
            subject="предмет", due=data["due"], text=data["text"]
        ),
        reply_markup=yes_no("hw_ok"),
    )


@router.callback_query(AddHw.confirm, F.data == "hw_ok:no")
async def hw_confirm_no(cb: CallbackQuery, state: FSMContext, user: User):
    await state.clear()
    await cb.message.answer(texts.CANCELLED, reply_markup=main_menu(user.is_admin))
    await cb.answer()


@router.callback_query(AddHw.confirm, F.data == "hw_ok:yes")
async def hw_confirm_yes(
    cb: CallbackQuery, state: FSMContext, session: AsyncSession, ai: AiClient, user: User, bot: Bot
):
    data = await state.get_data()
    await state.clear()
    subject = await session.get(Subject, data["subject_id"])
    due = date.fromisoformat(data["due"])
    text = data["text"]

    existing = list(
        await session.scalars(
            select(Homework).where(
                Homework.subject_id == subject.id, Homework.due_date == due
            )
        )
    )
    match: Homework | None = None
    for hw in existing:
        if await homework_ai.same_assignment(ai, session, hw.text, text):
            match = hw
            break

    if match is not None:
        if user.id not in (match.confirmed_by or []):
            match.confirmed_by = [*(match.confirmed_by or []), user.id]
            match.confirmations = len(match.confirmed_by) + 1
        newly_confirmed = match.status != HomeworkStatus.confirmed
        match.status = HomeworkStatus.confirmed
        if data.get("attachment"):
            match.attachments = [*(match.attachments or []), data["attachment"]]
        await session.commit()
        if newly_confirmed:
            await _publish(bot, subject, match)
            await cb.message.answer(
                texts.HW_CONFIRMED_PUBLISHED.format(subject=subject.name),
                reply_markup=main_menu(user.is_admin),
            )
        else:
            await cb.message.answer("Такое задание уже подтверждено 👍",
                                    reply_markup=main_menu(user.is_admin))
    else:
        hw = Homework(
            subject_id=subject.id,
            due_date=due,
            text=text,
            text_norm=homework_ai.normalize(text),
            created_by=user.id,
            confirmed_by=[user.id],
            attachments=[data["attachment"]] if data.get("attachment") else [],
        )
        session.add(hw)
        await session.commit()
        await cb.message.answer(
            texts.HW_SAVED_UNCONFIRMED, reply_markup=main_menu(user.is_admin)
        )
    await cb.answer()


async def _publish(bot: Bot, subject: Subject, hw: Homework) -> None:
    settings = get_settings()
    text = (
        f"📚 <b>{subject.name}</b> — задание к {hw.due_date.strftime('%d.%m')}\n\n{hw.text}"
    )
    try:
        if subject.thread_id and settings.supergroup_id:
            await bot.send_message(
                settings.supergroup_id, text, message_thread_id=subject.thread_id
            )
        elif settings.supergroup_id:
            await bot.send_message(settings.supergroup_id, text)
            for admin_id in settings.admin_ids:
                await bot.send_message(
                    admin_id,
                    f"Тема для «{subject.name}» не привязана — опубликовала в общий чат. "
                    f"Привяжи: /bind_subject {subject.name}",
                )
        else:
            return
        hw.published_at = datetime.now(UTC)
    except Exception:  # noqa: BLE001
        log.exception("publish homework failed")


@router.callback_query(F.data == "admin:hw", IsAdmin())
async def admin_hw_unconfirmed(cb: CallbackQuery, session: AsyncSession):
    items = list(
        await session.scalars(
            select(Homework)
            .where(Homework.status == HomeworkStatus.unconfirmed,
                   Homework.due_date >= date.today() - timedelta(days=1))
            .order_by(Homework.due_date)
        )
    )
    if not items:
        await cb.answer("Неподтверждённых заданий нет.", show_alert=True)
        return
    kb = InlineKeyboardBuilder()
    for hw in items:
        kb.button(
            text=f"✅ {hw.subject.name} к {hw.due_date.strftime('%d.%m')}",
            callback_data=f"hw_force:{hw.id}",
        )
    kb.adjust(1)
    await cb.message.answer(_fmt_hw_list(items), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("hw_force:"), IsAdmin())
async def admin_hw_force(cb: CallbackQuery, session: AsyncSession, bot: Bot):
    hw = await session.get(Homework, int(cb.data.split(":")[1]))
    if hw is None:
        await cb.answer("Не найдено.")
        return
    hw.status = HomeworkStatus.confirmed
    await session.commit()
    subject = await session.get(Subject, hw.subject_id)
    await _publish(bot, subject, hw)
    await session.commit()
    await cb.answer("Подтверждено и опубликовано.", show_alert=True)
