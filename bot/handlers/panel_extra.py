"""Панель старосты: список группы (импорт), дни рождения, праздники, картинки."""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.db.models import Holiday, MediaItem, User
from bot.filters import IsAdmin
from bot.keyboards.menu import cancel_menu
from bot.services.greetings import parse_birthday
from bot.utils.names import normalize_name

router = Router(name="panel_extra")

_MONTHS = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря"]
_DATE_TAIL = re.compile(r"(\d{1,2}[.\-/]\d{1,2}(?:[.\-/]\d{2,4})?)\s*$")


class ImportRoster(StatesGroup):
    waiting = State()


class AddHoliday(StatesGroup):
    title = State()
    date = State()
    message = State()


class UploadMedia(StatesGroup):
    waiting = State()


# ─────────────────── список группы + импорт ────────────────────────────


@router.callback_query(F.data == "p:roster", IsAdmin())
async def roster(cb: CallbackQuery, session: AsyncSession):
    users = list(
        await session.scalars(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
    )
    active = sum(1 for u in users if u.tg_id)
    lines = [f"<b>Список группы</b> — {len(users)} чел. "
             f"({active} активировали бота, {len(users) - active} только в списке)", ""]
    for i, u in enumerate(users, 1):
        mark = "" if u.tg_id else " ·нет в боте"
        bday = ""
        if u.birthday_day:
            bday = f" · 🎂 {u.birthday_day} {_MONTHS[u.birthday_month]}"
        lines.append(f"{i}. {u.full_name}{bday}{mark}")
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Загрузить список (с ДР)", callback_data="p:roster_import")
    kb.button(text=texts.BTN_BACK, callback_data="p:home")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "p:roster_import", IsAdmin())
async def roster_import_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ImportRoster.waiting)
    await cb.message.answer(
        "Пришли список группы — по одному человеку на строку. Дата рождения "
        "необязательна, через <code>;</code> или тире:\n\n"
        "<code>Иванова Мария Петровна; 15.09.2005\n"
        "Петров Пётр Петрович — 03.12\n"
        "Сидорова Анна Ивановна</code>\n\n"
        "Существующие записи обновятся, новые добавятся.",
        reply_markup=cancel_menu(),
    )
    await cb.answer()


@router.message(ImportRoster.waiting, F.text)
async def roster_import_apply(message: Message, state: FSMContext, session: AsyncSession):
    from bot.keyboards.menu import main_menu

    existing = {u.full_name_norm: u for u in await session.scalars(select(User))}
    added = updated = bad = 0
    for raw in message.text.splitlines():
        line = raw.strip()
        if not line:
            continue
        bday = None
        m = _DATE_TAIL.search(line)
        if m:
            bday = parse_birthday(m.group(1))
            name = line[: m.start()].rstrip(" ;,—-\t")
        else:
            name = line
        parts = name.split()
        if not (2 <= len(parts) <= 4):
            bad += 1
            continue
        norm = normalize_name(name)
        user = existing.get(norm)
        if user is None:
            user = User(full_name=name, full_name_norm=norm)
            session.add(user)
            existing[norm] = user
            added += 1
        else:
            updated += 1
        if bday:
            user.birthday_day, user.birthday_month, user.birthday_year = bday
    await session.commit()
    await state.clear()
    await message.answer(
        f"Готово. Добавлено: {added}, обновлено: {updated}"
        + (f", не разобрала строк: {bad}" if bad else ""),
        reply_markup=main_menu(True),
    )


# ─────────────────────── дни рождения (обзор) ──────────────────────────


@router.callback_query(F.data == "p:bdays", IsAdmin())
async def bdays_overview(cb: CallbackQuery, session: AsyncSession):
    users = list(await session.scalars(select(User).where(User.is_active.is_(True))))
    have = [u for u in users if u.birthday_day]
    missing = [u.full_name for u in users if not u.birthday_day]
    lines = [f"🎂 Дни рождения указаны у {len(have)} из {len(users)}.", ""]
    for u in sorted(have, key=lambda x: (x.birthday_month, x.birthday_day)):
        y = f".{u.birthday_year}" if u.birthday_year else ""
        lines.append(f"• {u.full_name} — {u.birthday_day:02d}.{u.birthday_month:02d}{y}")
    if missing:
        lines += ["", "<b>Нет даты:</b> " + ", ".join(missing[:30])]
    lines += ["", "Загрузить сразу всем — «Список группы» → «Загрузить список (с ДР)»."]
    await cb.message.answer("\n".join(lines))
    await cb.answer()


# ─────────────────────────── праздники ────────────────────────────────


@router.callback_query(F.data == "p:holidays", IsAdmin())
async def holidays_list(cb: CallbackQuery, session: AsyncSession):
    hs = list(await session.scalars(select(Holiday).order_by(Holiday.month, Holiday.day)))
    lines = ["<b>🎉 Праздники</b>", ""]
    kb = InlineKeyboardBuilder()
    for h in hs:
        state = "" if h.is_active else " (выкл)"
        lines.append(f"#{h.id} · {h.day:02d}.{h.month:02d} — {h.title}{state}")
        kb.button(text=f"🗑 {h.title}", callback_data=f"hol_del:{h.id}")
    kb.button(text="➕ Добавить праздник", callback_data="hol_add")
    kb.button(text=texts.BTN_BACK, callback_data="p:home")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "hol_add", IsAdmin())
async def hol_add_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddHoliday.title)
    await cb.message.answer("Название праздника:", reply_markup=cancel_menu())
    await cb.answer()


@router.message(AddHoliday.title, F.text)
async def hol_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddHoliday.date)
    await message.answer("Дата в формате <code>ДД.ММ</code>:")


@router.message(AddHoliday.date, F.text)
async def hol_add_date(message: Message, state: FSMContext):
    parsed = parse_birthday(message.text)  # тот же формат ДД.ММ
    if not parsed:
        await message.answer("Не поняла. Формат: <code>25.01</code>")
        return
    day, month, _ = parsed
    await state.update_data(day=day, month=month)
    await state.set_state(AddHoliday.message)
    await message.answer("Текст поздравления, который бот отправит в чат:")


@router.message(AddHoliday.message, F.text)
async def hol_add_save(message: Message, state: FSMContext, session: AsyncSession):
    from bot.keyboards.menu import main_menu

    data = await state.get_data()
    session.add(Holiday(title=data["title"], month=data["month"], day=data["day"],
                        message=message.text.strip()))
    await session.commit()
    await state.clear()
    await message.answer("Добавила праздник.", reply_markup=main_menu(True))


@router.callback_query(F.data.startswith("hol_del:"), IsAdmin())
async def hol_del(cb: CallbackQuery, session: AsyncSession):
    h = await session.get(Holiday, int(cb.data.split(":")[1]))
    if h:
        await session.delete(h)
        await session.commit()
        await cb.answer("Удалила.")
        await cb.message.edit_reply_markup(reply_markup=None)
    else:
        await cb.answer("Не найдено.")


# ─────────────────────────── картинки ─────────────────────────────────


@router.callback_query(F.data == "p:media", IsAdmin())
async def media_menu(cb: CallbackQuery, session: AsyncSession):
    n_b = await session.scalar(
        select(func.count()).select_from(MediaItem).where(MediaItem.kind == "birthday")
    )
    n_m = await session.scalar(
        select(func.count()).select_from(MediaItem).where(MediaItem.kind == "meme")
    )
    kb = InlineKeyboardBuilder()
    kb.button(text=f"🎂 Картинки для ДР ({n_b})", callback_data="media_add:birthday")
    kb.button(text=f"😎 Мемы ({n_m})", callback_data="media_add:meme")
    kb.button(text="🧹 Очистить картинки ДР", callback_data="media_clear:birthday")
    kb.button(text="🧹 Очистить мемы", callback_data="media_clear:meme")
    kb.button(text=texts.BTN_BACK, callback_data="p:home")
    kb.adjust(1)
    await cb.message.answer(
        "🖼 <b>Картинки</b>\nОтправляй фото — я сохраню. Для ДР берётся случайное "
        "в день рождения, «мем дня» — по кнопке у студентов.",
        reply_markup=kb.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("media_add:"), IsAdmin())
async def media_add_start(cb: CallbackQuery, state: FSMContext):
    kind = cb.data.split(":")[1]
    await state.set_state(UploadMedia.waiting)
    await state.update_data(kind=kind)
    label = "для дней рождения" if kind == "birthday" else "с мемами"
    await cb.message.answer(
        f"Пришли одну или несколько картинок {label}. Когда закончишь — нажми «Отмена».",
        reply_markup=cancel_menu(),
    )
    await cb.answer()


@router.message(UploadMedia.waiting, F.photo)
async def media_add_save(message: Message, state: FSMContext, session: AsyncSession, user: User):
    data = await state.get_data()
    session.add(
        MediaItem(kind=data["kind"], file_id=message.photo[-1].file_id, added_by=user.id)
    )
    await session.commit()
    await message.answer("Сохранила ✅ (пришли ещё или «Отмена»)")


@router.callback_query(F.data.startswith("media_clear:"), IsAdmin())
async def media_clear(cb: CallbackQuery, session: AsyncSession):
    kind = cb.data.split(":")[1]
    await session.execute(delete(MediaItem).where(MediaItem.kind == kind))
    await session.commit()
    await cb.answer("Очищено.", show_alert=True)
