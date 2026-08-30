"""База знаний — раздел панели старосты: обновить с сайта, добавить/удалить запись,
дополнить преподавателя данными с его страницы."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import get_settings
from bot.db.models import KbCategory, KbEntry
from bot.db.session import get_sessionmaker
from bot.filters import IsAdmin
from bot.keyboards.menu import cancel_menu
from bot.services.ai.client import AiClient
from bot.services.kb_import.university_site import enrich_teacher, refresh_from_site

router = Router(name="kb_admin")


class AddKb(StatesGroup):
    title = State()
    body = State()


class EnrichKb(StatesGroup):
    query = State()


# ─────────────────────────── обновить с сайта ───────────────────────────


@router.callback_query(F.data == "p:kb_refresh", IsAdmin())
async def kb_refresh(cb: CallbackQuery):
    await cb.answer()
    if not get_settings().kb_school_url:
        await cb.message.answer(
            "Не задан адрес страницы факультета (KB_SCHOOL_URL в .env). "
            "Пока наполняй базу вручную — кнопка «Добавить запись»."
        )
        return
    await cb.message.answer("Обновляю базу с сайта вуза, это займёт минуту…")
    n = await refresh_from_site(get_sessionmaker())
    await cb.message.answer(
        f"Готово: {n} записей (преподаватели + контакты дирекции).\n\n"
        f"Чтобы добавить преподавателю почту, кабинет, часы приёма и предметы — "
        f"кнопка «Дополнить преподавателя»."
    )


# ─────────────────────────── добавить вручную ──────────────────────────


@router.callback_query(F.data == "p:kb_add", IsAdmin())
async def kb_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddKb.title)
    await cb.message.answer(
        "Заголовок записи (например «Деканат» или «Иванов Иван Иванович»):",
        reply_markup=cancel_menu(),
    )
    await cb.answer()


@router.message(AddKb.title, F.text)
async def kb_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddKb.body)
    await message.answer("Текст записи (факты: кафедра, часы работы, кабинет, контакты…):")


@router.message(AddKb.body, F.text)
async def kb_add_body(message: Message, state: FSMContext, session: AsyncSession):
    from bot.keyboards.menu import main_menu

    data = await state.get_data()
    title = data["title"]
    low = title.lower()
    category = KbCategory.general
    if any(w in low for w in ("деканат", "кафедра", "учебн", "отдел", "дирекц")):
        category = KbCategory.department
    elif len(title.split()) == 3 and all(p[:1].isupper() for p in title.split()):
        category = KbCategory.teacher
    session.add(
        KbEntry(category=category, title=title, body=message.text.strip(), source="manual")
    )
    await session.commit()
    await state.clear()
    await message.answer("Записала в базу знаний.", reply_markup=main_menu(True))


# ─────────────────────── дополнить преподавателя ───────────────────────


@router.callback_query(F.data == "p:kb_enrich", IsAdmin())
async def kb_enrich_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(EnrichKb.query)
    await cb.message.answer(texts.KB_ENRICH_ASK, reply_markup=cancel_menu())
    await cb.answer()


@router.message(EnrichKb.query, F.text)
async def kb_enrich_run(message: Message, state: FSMContext, ai: AiClient):
    from bot.keyboards.menu import main_menu

    await state.clear()
    await message.answer("Смотрю страницу преподавателя…")
    result = await enrich_teacher(get_sessionmaker(), ai, message.text.strip())
    await message.answer(result, reply_markup=main_menu(True))


# ─────────────────────────── список / удаление ─────────────────────────


@router.callback_query(F.data == "p:kb_list", IsAdmin())
async def kb_list(cb: CallbackQuery, session: AsyncSession):
    entries = list(
        await session.scalars(select(KbEntry).order_by(KbEntry.category, KbEntry.title))
    )
    if not entries:
        await cb.message.answer("База знаний пустая.")
        await cb.answer()
        return
    manual = [e for e in entries if e.source == "manual"]
    lines = [f"<b>База знаний</b> — {len(entries)} записей "
             f"({len(entries) - len(manual)} с сайта, {len(manual)} вручную)", ""]
    for e in manual[:40]:
        lines.append(f"#{e.id} · {e.title}")
    if manual:
        lines.append("\nУдалить запись — нажми на неё ниже:")
    kb = InlineKeyboardBuilder()
    for e in manual[:40]:
        kb.button(text=f"🗑 {e.title[:40]}", callback_data=f"kbdel:{e.id}")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup() if manual else None)
    await cb.answer()


@router.callback_query(F.data.startswith("kbdel:"), IsAdmin())
async def kb_del(cb: CallbackQuery, session: AsyncSession):
    entry = await session.get(KbEntry, int(cb.data.split(":")[1]))
    if entry:
        await session.delete(entry)
        await session.commit()
        await cb.answer("Удалила.")
        await cb.message.edit_reply_markup(reply_markup=None)
    else:
        await cb.answer("Не найдено.")
