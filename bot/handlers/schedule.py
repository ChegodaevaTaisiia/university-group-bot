"""Расписание: просмотр всеми, редактирование старостой (пошагово + импорт текстом)."""

from __future__ import annotations

import re
from datetime import date, time, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import get_settings
from bot.db.models import Lesson, Subject, User, WeekParity
from bot.filters import IsAdmin, IsRegistered
from bot.keyboards.menu import cancel_menu, main_menu
from bot.services.schedule_repo import (
    format_day,
    lessons_for_day,
    lessons_for_week,
)

router = Router(name="schedule")
router.message.filter(IsRegistered())


def _nav_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="sch:today")
    kb.button(text="Завтра", callback_data="sch:tomorrow")
    kb.button(text="Неделя", callback_data="sch:week")
    kb.adjust(3)
    return kb


@router.message(F.text.casefold() == texts.BTN_SCHEDULE.casefold())
@router.message(Command("schedule"))
async def schedule_root(message: Message, session: AsyncSession):
    await _send_day(message, session, date.today())


async def _send_day(message: Message, session: AsyncSession, on: date):
    settings = get_settings()
    day = await lessons_for_day(session, on, settings.semester_start)
    await message.answer(format_day(day), reply_markup=_nav_kb().as_markup())


@router.callback_query(F.data.startswith("sch:"))
async def schedule_nav(cb: CallbackQuery, session: AsyncSession):
    settings = get_settings()
    action = cb.data.split(":", 1)[1]
    today = date.today()
    if action == "today":
        text = format_day(await lessons_for_day(session, today, settings.semester_start))
    elif action == "tomorrow":
        text = format_day(
            await lessons_for_day(session, today + timedelta(days=1), settings.semester_start)
        )
    else:
        monday = today - timedelta(days=today.weekday())
        days = await lessons_for_week(session, monday, settings.semester_start)
        text = "\n\n".join(format_day(d) for d in days)
    await cb.message.edit_text(text, reply_markup=_nav_kb().as_markup())
    await cb.answer()


# ─────────────────────────── редактирование ──────────────────────────────

_IMPORT_HELP = (
    "Пришли расписание текстом — по строке на пару, формат:\n\n"
    "<code>день;пара;время;предмет;чётность;тип;аудитория;преподаватель</code>\n\n"
    "• день: пн вт ср чт пт сб\n"
    "• чётность: <code>-</code> (каждую), <code>ч</code> (числитель), <code>з</code> (знаменатель)\n"
    "• лишние поля можно опускать справа\n\n"
    "Пример:\n"
    "<code>пн;1;9:00;Матанализ;-;лекция;301;Иванов И.И.</code>\n"
    "<code>пн;2;10:40;Физика;ч;практика;212</code>\n\n"
    "⚠️ Импорт заменит всё текущее расписание."
)

_DAYS = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
_PARITY = {"-": WeekParity.any, "ч": WeekParity.odd, "з": WeekParity.even}


class SchedImport(StatesGroup):
    waiting_text = State()


@router.message(Command("schedule_import"), IsAdmin())
async def sched_import_start(message: Message, state: FSMContext):
    await message.answer(_IMPORT_HELP, reply_markup=cancel_menu())
    await state.set_state(SchedImport.waiting_text)


@router.callback_query(F.data == "p:sched_import", IsAdmin())
async def sched_import_start_cb(cb: CallbackQuery, state: FSMContext):
    await cb.message.answer(_IMPORT_HELP, reply_markup=cancel_menu())
    await state.set_state(SchedImport.waiting_text)
    await cb.answer()


@router.callback_query(F.data == "p:sched_rasp", IsAdmin())
async def sched_rasp_cb(cb: CallbackQuery):
    from bot.config import get_settings
    from bot.db.session import get_sessionmaker
    from bot.services.rasp.sync import sync_schedule

    await cb.answer()
    if not get_settings().rasp_url:
        await cb.message.answer(
            "Не задана ссылка на расписание. Добавь в .env строку\n"
            "<code>RASP_URL=https://rasp.rea.ru/?q=твоя-группа</code>\n"
            "(скопируй адрес со страницы своей группы на rasp.rea.ru)."
        )
        return
    await cb.message.answer("Загружаю расписание с rasp.rea.ru, это займёт ~минуту…")
    res = await sync_schedule(get_sessionmaker(), cb.bot)
    await cb.message.answer(res)


def _parse_time(s: str) -> time:
    m = re.match(r"(\d{1,2})[:.\s](\d{2})", s.strip())
    if not m:
        raise ValueError(f"время: {s!r}")
    return time(int(m.group(1)), int(m.group(2)))


@router.message(SchedImport.waiting_text, F.text)
async def sched_import_apply(message: Message, state: FSMContext, session: AsyncSession, user: User):
    rows = [r.strip() for r in message.text.splitlines() if r.strip()]
    parsed: list[dict] = []
    errors: list[str] = []
    for i, row in enumerate(rows, 1):
        parts = [p.strip() for p in row.split(";")]
        try:
            day = _DAYS[parts[0].lower()]
            pair_no = int(parts[1])
            starts = _parse_time(parts[2])
            subject_name = parts[3]
            if not subject_name:
                raise ValueError("нет предмета")
            parity = _PARITY.get(parts[4].lower(), WeekParity.any) if len(parts) > 4 else WeekParity.any
            kind = parts[5] if len(parts) > 5 and parts[5] else None
            room = parts[6] if len(parts) > 6 and parts[6] else None
            teacher = parts[7] if len(parts) > 7 and parts[7] else None
        except (KeyError, ValueError, IndexError) as e:
            errors.append(f"строка {i}: {e}")
            continue
        parsed.append(dict(day=day, pair_no=pair_no, starts=starts, subject_name=subject_name,
                           parity=parity, kind=kind, room=room, teacher=teacher))

    if errors:
        await message.answer("Не смогла разобрать:\n" + "\n".join(errors[:10]))
        return

    # применяем
    subjects: dict[str, Subject] = {
        s.name: s for s in await session.scalars(select(Subject))
    }
    await session.execute(delete(Lesson))
    for p in parsed:
        subj = subjects.get(p["subject_name"])
        if subj is None:
            subj = Subject(name=p["subject_name"])
            session.add(subj)
            await session.flush()
            subjects[subj.name] = subj
        session.add(Lesson(
            subject_id=subj.id, weekday=p["day"], pair_no=p["pair_no"],
            starts_at=p["starts"], week_parity=p["parity"], kind=p["kind"],
            room=p["room"], teacher=p["teacher"],
        ))
    await session.commit()
    await state.clear()
    await message.answer(
        f"Готово: {len(parsed)} пар, предметов — {len(subjects)}.",
        reply_markup=main_menu(user.is_admin),
    )


async def _publish_week(bot, session: AsyncSession) -> str:
    settings = get_settings()
    if settings.supergroup_id is None:
        return "Группа не подключена (нет SUPERGROUP_ID в .env)."
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = await lessons_for_week(session, monday, settings.semester_start)
    text = "<b>📅 Расписание на неделю</b>\n\n" + "\n\n".join(format_day(d) for d in days)
    await bot.send_message(settings.supergroup_id, text)
    return "Опубликовала расписание в чат группы."


@router.message(Command("schedule_post"), IsAdmin())
async def schedule_post(message: Message, session: AsyncSession):
    await message.answer(await _publish_week(message.bot, session))


@router.callback_query(F.data == "p:sched_post", IsAdmin())
async def schedule_post_cb(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    await cb.message.answer(await _publish_week(cb.bot, session))
