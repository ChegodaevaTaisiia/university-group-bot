"""Расписание: просмотр всеми, редактирование старостой (пошагово + импорт текстом)."""

from __future__ import annotations

import contextlib
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


def _day_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="sch:today")
    kb.button(text="Завтра", callback_data="sch:tomorrow")
    kb.button(text="📆 Эта неделя", callback_data="sch:w:0")
    kb.button(text="След. неделя ▶️", callback_data="sch:w:1")
    kb.adjust(2, 2)
    return kb


def _week_kb(offset: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="◀️ Пред.", callback_data=f"sch:w:{offset - 1}")
    kb.button(text="Сегодня", callback_data="sch:today")
    kb.button(text="След. ▶️", callback_data=f"sch:w:{offset + 1}")
    kb.adjust(3)
    return kb


async def _nearest_week_offset(session: AsyncSession, monday: date, sem: date) -> int:
    """Если на текущей неделе пар нет — ищем ближайшую вперёд (до 3 недель)."""
    for off in range(4):
        days = await lessons_for_week(session, monday + timedelta(weeks=off), sem)
        if any(d.lessons for d in days):
            return off
    return 0


@router.message(F.text.casefold() == texts.BTN_SCHEDULE.casefold())
@router.message(Command("schedule"))
async def schedule_root(message: Message, session: AsyncSession):
    settings = get_settings()
    today = date.today()
    day = await lessons_for_day(session, today, settings.semester_start)
    if day.lessons:
        await message.answer(format_day(day), reply_markup=_day_kb().as_markup())
        return
    # сегодня пусто — показываем ближайшую неделю с парами
    monday = today - timedelta(days=today.weekday())
    off = await _nearest_week_offset(session, monday, settings.semester_start)
    await _send_week(message, session, off)


async def _send_week(target, session: AsyncSession, offset: int) -> None:  # noqa: ANN001
    settings = get_settings()
    today = date.today()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
    days = await lessons_for_week(session, monday, settings.semester_start)
    when = "эта неделя" if offset == 0 else (
        "следующая неделя" if offset == 1 else f"неделя с {monday.strftime('%d.%m')}"
    )
    await target.answer(f"<b>📅 Расписание — {when}</b>")
    for i, day in enumerate(days):
        await target.answer(
            format_day(day),
            reply_markup=_week_kb(offset).as_markup() if i == len(days) - 1 else None,
        )


@router.callback_query(F.data.startswith("sch:w:"))
async def schedule_week(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    offset = int(cb.data.split(":")[2])
    with contextlib.suppress(Exception):
        await cb.message.edit_reply_markup(reply_markup=None)
    await _send_week(cb.message, session, offset)


@router.callback_query(F.data.in_({"sch:today", "sch:tomorrow"}))
async def schedule_day(cb: CallbackQuery, session: AsyncSession):
    settings = get_settings()
    await cb.answer()
    on = date.today() + (timedelta(days=1) if cb.data == "sch:tomorrow" else timedelta())
    day = await lessons_for_day(session, on, settings.semester_start)
    with contextlib.suppress(Exception):
        await cb.message.edit_text(format_day(day), reply_markup=_day_kb().as_markup())


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


async def _publish_week(bot, session: AsyncSession) -> str:  # noqa: ANN001
    settings = get_settings()
    if settings.supergroup_id is None:
        return "Группа не подключена (нет SUPERGROUP_ID в .env)."
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    days = await lessons_for_week(session, monday, settings.semester_start)
    parity = days[0].parity if days else None
    from bot import texts as _t

    label = _t.WEEK_ODD if parity == WeekParity.odd else _t.WEEK_EVEN
    await bot.send_message(
        settings.supergroup_id, f"<b>📅 Расписание на неделю</b> · {label}"
    )
    for day in days:
        await bot.send_message(settings.supergroup_id, format_day(day))
    return "Опубликовала расписание в чат группы."


@router.message(Command("schedule_post"), IsAdmin())
async def schedule_post(message: Message, session: AsyncSession):
    await message.answer(await _publish_week(message.bot, session))


@router.callback_query(F.data == "p:sched_post", IsAdmin())
async def schedule_post_cb(cb: CallbackQuery, session: AsyncSession):
    await cb.answer()
    await cb.message.answer(await _publish_week(cb.bot, session))
