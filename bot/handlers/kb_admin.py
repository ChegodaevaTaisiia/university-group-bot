"""База знаний — управление старостой: список, добавить, удалить, обновить с сайта."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import KbCategory, KbEntry
from bot.filters import IsAdmin
from bot.keyboards.menu import cancel_menu
from bot.services.ai.client import AiClient

router = Router(name="kb_admin")


class AddKb(StatesGroup):
    title = State()
    body = State()


@router.message(Command("kb"), IsAdmin())
@router.callback_query(F.data == "admin:kb", IsAdmin())
async def kb_list(event: Message | CallbackQuery, session: AsyncSession):
    message = event if isinstance(event, Message) else event.message
    entries = list(await session.scalars(select(KbEntry).order_by(KbEntry.category, KbEntry.title)))
    lines = [f"<b>База знаний</b> — {len(entries)} записей", ""]
    for e in entries[:50]:
        lines.append(f"#{e.id} [{e.category.value}] {e.title}")
    lines += ["", "Добавить: /kb_add", "Удалить: /kb_del <id>", "Обновить с сайта: /kb_refresh"]
    await message.answer("\n".join(lines))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.message(Command("kb_add"), IsAdmin())
async def kb_add_start(message: Message, state: FSMContext):
    await state.set_state(AddKb.title)
    await message.answer(
        "Заголовок записи (например «Деканат ФКН» или «Иванов Иван Иванович»):",
        reply_markup=cancel_menu(),
    )


@router.message(AddKb.title, F.text)
async def kb_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddKb.body)
    await message.answer("Текст записи (факты: кафедра, часы работы, кабинет, контакты…):")


@router.message(AddKb.body, F.text)
async def kb_add_body(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    title = data["title"]
    low = title.lower()
    category = KbCategory.general
    if any(w in low for w in ("деканат", "кафедра", "учебн", "отдел")):
        category = KbCategory.department
    elif len(title.split()) == 3 and all(p[:1].isupper() for p in title.split()):
        category = KbCategory.teacher
    session.add(
        KbEntry(category=category, title=title, body=message.text.strip(), source="manual")
    )
    await session.commit()
    await state.clear()
    await message.answer("Записала в базу знаний.")


@router.message(Command("kb_del"), IsAdmin())
async def kb_del(message: Message, session: AsyncSession):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: /kb_del <id>")
        return
    entry = await session.get(KbEntry, int(parts[1]))
    if entry:
        await session.delete(entry)
        await session.commit()
        await message.answer("Удалила.")
    else:
        await message.answer("Не найдено.")


@router.message(Command("kb_refresh"), IsAdmin())
async def kb_refresh(message: Message):
    from bot.config import get_settings
    from bot.db.session import get_sessionmaker
    from bot.services.kb_import.university_site import refresh_from_site

    if not get_settings().kb_school_url:
        await message.answer(
            "KB_SCHOOL_URL не задан в .env. Укажи ссылку на страницу своей высшей школы "
            "на сайте вуза, либо наполняй базу вручную через /kb_add."
        )
        return
    await message.answer("Обновляю базу с сайта, это займёт минуту…")
    n = await refresh_from_site(get_sessionmaker())
    await message.answer(
        f"Готово: {n} записей (преподаватели + контакты).\n"
        f"Данные по конкретному преподу (почта, кабинет, часы, предметы): "
        f"/kb_enrich <фамилия>"
    )


@router.message(Command("kb_enrich"), IsAdmin())
async def kb_enrich(message: Message, ai: AiClient):
    from bot.db.session import get_sessionmaker
    from bot.services.kb_import.university_site import enrich_teacher

    query = message.text.partition(" ")[2].strip()
    if not query:
        await message.answer("Формат: /kb_enrich <фамилия или часть ФИО>")
        return
    await message.answer("Смотрю страницу преподавателя…")
    result = await enrich_teacher(get_sessionmaker(), ai, query)
    await message.answer(result)
