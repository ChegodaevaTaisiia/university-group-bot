"""Панель старосты: закреплённые задания, списки тем, очереди на защиту."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot import texts
from bot.config import get_settings
from bot.db.models import (
    DefenseEvent,
    PinnedTask,
    Subject,
    TopicItem,
    TopicList,
    User,
)
from bot.filters import IsAdmin
from bot.keyboards.menu import cancel_menu, main_menu, panel_queues
from bot.services import queues
from bot.utils.dates import parse_when

router = Router(name="panel_queues")


class NewPinned(StatesGroup):
    subject = State()
    title = State()
    text = State()
    deadline = State()


class NewTopics(StatesGroup):
    subject = State()
    title = State()
    deadline = State()
    items = State()


class NewDefense(StatesGroup):
    subject = State()
    title = State()
    description = State()
    slots = State()


class AddSlots(StatesGroup):
    waiting = State()


async def _subjects(session: AsyncSession) -> list[Subject]:
    return list(
        await session.scalars(
            select(Subject).where(Subject.is_active.is_(True)).order_by(Subject.name)
        )
    )


def _subject_kb(subjects: list[Subject], prefix: str) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for s in subjects:
        kb.button(text=s.name, callback_data=f"{prefix}:{s.id}")
    kb.button(text="— без предмета —", callback_data=f"{prefix}:0")
    kb.adjust(2)
    return kb


def _opt_date(text: str):  # noqa: ANN001
    text = text.strip().lower()
    if text in ("-", "нет", "без срока", "не надо"):
        return None
    d = parse_when(text, get_settings().tz)
    return d.date() if d else False


# ───────────────────────── навигация ──────────────────────────────────


@router.callback_query(F.data == "p:queues", IsAdmin())
async def q_home(cb: CallbackQuery):
    await cb.message.edit_text("🎓 <b>Сдачи и темы</b>", reply_markup=panel_queues())
    await cb.answer()


# ─────────────────── закреплённые задания ─────────────────────────────


@router.callback_query(F.data == "pq:pinned", IsAdmin())
async def pinned_list(cb: CallbackQuery, session: AsyncSession):
    rows = list(
        await session.scalars(
            select(PinnedTask).options(selectinload(PinnedTask.subject))
            .where(PinnedTask.is_active.is_(True)).order_by(PinnedTask.subject_id)
        )
    )
    lines = ["📌 <b>Закреплённые задания</b>", ""]
    kb = InlineKeyboardBuilder()
    for t in rows:
        dl = f" (до {t.deadline.strftime('%d.%m')})" if t.deadline else ""
        lines.append(f"#{t.id} · {t.subject.name}: {t.title}{dl}")
        kb.button(text=f"🗑 {t.title[:35]}", callback_data=f"pq:pin_del:{t.id}")
    kb.button(text="➕ Добавить", callback_data="pq:pin_add")
    kb.button(text=texts.BTN_BACK, callback_data="p:queues")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "pq:pin_add", IsAdmin())
async def pin_add(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    subs = await _subjects(session)
    if not subs:
        await cb.answer("Сначала загрузи расписание — появятся предметы.", show_alert=True)
        return
    await state.set_state(NewPinned.subject)
    await cb.message.answer("По какому предмету?",
                            reply_markup=_subject_kb(subs, "pinsub").as_markup())
    await cb.answer()


@router.callback_query(NewPinned.subject, F.data.startswith("pinsub:"))
async def pin_subject(cb: CallbackQuery, state: FSMContext):
    sid = int(cb.data.split(":")[1])
    await state.update_data(subject_id=sid or None)
    await state.set_state(NewPinned.title)
    await cb.message.answer("Название задания (например «Реферат по теме курса»):",
                            reply_markup=cancel_menu())
    await cb.answer()


@router.message(NewPinned.title, F.text)
async def pin_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(NewPinned.text)
    await message.answer("Подробности (требования, объём и т.п.). Или «-» если не надо:")


@router.message(NewPinned.text, F.text)
async def pin_text(message: Message, state: FSMContext):
    txt = "" if message.text.strip() == "-" else message.text.strip()
    await state.update_data(text=txt)
    await state.set_state(NewPinned.deadline)
    await message.answer("Срок сдачи? (<code>25.12</code>, <code>конец семестра</code> или «-»)")


@router.message(NewPinned.deadline, F.text)
async def pin_deadline(message: Message, state: FSMContext, session: AsyncSession, user: User):
    dl = _opt_date(message.text)
    if dl is False:
        await message.answer("Не поняла дату. <code>25.12</code> или «-».")
        return
    data = await state.get_data()
    session.add(PinnedTask(
        subject_id=data["subject_id"], title=data["title"], text=data["text"],
        deadline=dl, created_by=user.id,
    ))
    await session.commit()
    await state.clear()
    await message.answer("Закрепила задание.", reply_markup=main_menu(True))


@router.callback_query(F.data.startswith("pq:pin_del:"), IsAdmin())
async def pin_del(cb: CallbackQuery, session: AsyncSession):
    t = await session.get(PinnedTask, int(cb.data.split(":")[2]))
    if t:
        await session.delete(t)
        await session.commit()
        await cb.answer("Удалила.")
        await cb.message.edit_reply_markup(reply_markup=None)


# ────────────────────────── списки тем ───────────────────────────────


@router.callback_query(F.data == "pq:topics", IsAdmin())
async def topics_list(cb: CallbackQuery, session: AsyncSession):
    rows = list(
        await session.scalars(
            select(TopicList).options(selectinload(TopicList.subject))
            .order_by(TopicList.id.desc())
        )
    )
    lines = ["📝 <b>Списки тем</b>", ""]
    kb = InlineKeyboardBuilder()
    for lst in rows:
        free, total = await queues.free_topics_count(session, lst)
        subj = f"{lst.subject.name} · " if lst.subject else ""
        state = "" if lst.is_open else " (закрыт)"
        lines.append(f"#{lst.id} · {subj}{lst.title} — {free}/{total} свободно{state}")
        kb.button(text=f"👁 {lst.title[:30]}", callback_data=f"pq:tl_view:{lst.id}")
    kb.button(text="➕ Новый список", callback_data="pq:tl_add")
    kb.button(text=texts.BTN_BACK, callback_data="p:queues")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("pq:tl_view:"), IsAdmin())
async def tl_view(cb: CallbackQuery, session: AsyncSession):
    lst_id = int(cb.data.split(":")[2])
    lst = await session.get(TopicList, lst_id)
    items = list(
        await session.scalars(
            select(TopicItem).options(selectinload(TopicItem.student))
            .where(TopicItem.list_id == lst_id).order_by(TopicItem.position)
        )
    )
    lines = [f"📝 <b>{lst.title}</b>", ""]
    kb = InlineKeyboardBuilder()
    for it in items:
        who = it.student.full_name if it.student else "свободно"
        lines.append(f"{it.position}. {it.text} — {who}")
        if it.student:
            kb.button(text=f"↩️ Освободить #{it.position}", callback_data=f"pq:tl_free:{it.id}")
    kb.button(
        text="🔒 Закрыть список" if lst.is_open else "🔓 Открыть список",
        callback_data=f"pq:tl_toggle:{lst_id}",
    )
    kb.button(text="🗑 Удалить список", callback_data=f"pq:tl_del:{lst_id}")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("pq:tl_free:"), IsAdmin())
async def tl_free(cb: CallbackQuery, session: AsyncSession):
    it = await session.get(TopicItem, int(cb.data.split(":")[2]))
    if it:
        it.taken_by = None
        it.taken_at = None
        await session.commit()
    await cb.answer("Тема снова свободна.")


@router.callback_query(F.data.startswith("pq:tl_toggle:"), IsAdmin())
async def tl_toggle(cb: CallbackQuery, session: AsyncSession):
    lst = await session.get(TopicList, int(cb.data.split(":")[2]))
    if lst:
        lst.is_open = not lst.is_open
        await session.commit()
    await cb.answer("Готово.")


@router.callback_query(F.data.startswith("pq:tl_del:"), IsAdmin())
async def tl_del(cb: CallbackQuery, session: AsyncSession):
    lst = await session.get(TopicList, int(cb.data.split(":")[2]))
    if lst:
        await session.delete(lst)
        await session.commit()
        await cb.answer("Удалила список.")
        await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "pq:tl_add", IsAdmin())
async def tl_add(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.set_state(NewTopics.subject)
    await cb.message.answer(
        "По какому предмету?",
        reply_markup=_subject_kb(await _subjects(session), "tlsub").as_markup(),
    )
    await cb.answer()


@router.callback_query(NewTopics.subject, F.data.startswith("tlsub:"))
async def tl_subject(cb: CallbackQuery, state: FSMContext):
    await state.update_data(subject_id=int(cb.data.split(":")[1]) or None)
    await state.set_state(NewTopics.title)
    await cb.message.answer("Название списка (например «Темы рефератов»):",
                            reply_markup=cancel_menu())
    await cb.answer()


@router.message(NewTopics.title, F.text)
async def tl_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(NewTopics.deadline)
    await message.answer("Срок? (<code>25.12</code> или «-»)")


@router.message(NewTopics.deadline, F.text)
async def tl_deadline(message: Message, state: FSMContext):
    dl = _opt_date(message.text)
    if dl is False:
        await message.answer("Не поняла дату.")
        return
    await state.update_data(deadline=dl.isoformat() if dl else None)
    await state.set_state(NewTopics.items)
    await message.answer("Пришли темы — по одной на строку.")


@router.message(NewTopics.items, F.text)
async def tl_items(message: Message, state: FSMContext, session: AsyncSession, user: User):
    from datetime import date as _date

    items = [x.strip() for x in message.text.splitlines() if x.strip()]
    if not items:
        await message.answer("Пусто. Пришли список тем.")
        return
    data = await state.get_data()
    lst = TopicList(
        subject_id=data["subject_id"], title=data["title"],
        deadline=_date.fromisoformat(data["deadline"]) if data["deadline"] else None,
        created_by=user.id,
    )
    session.add(lst)
    await session.flush()
    for i, txt in enumerate(items, 1):
        session.add(TopicItem(list_id=lst.id, position=i, text=txt))
    await session.commit()
    await state.clear()
    await message.answer(f"Создала список: {len(items)} тем.", reply_markup=main_menu(True))


# ─────────────────────── очереди на защиту ───────────────────────────


@router.callback_query(F.data == "pq:defense", IsAdmin())
async def defense_list(cb: CallbackQuery, session: AsyncSession):
    rows = list(
        await session.scalars(
            select(DefenseEvent).options(selectinload(DefenseEvent.subject))
            .order_by(DefenseEvent.id.desc())
        )
    )
    lines = ["🎓 <b>Очереди на защиту</b>", ""]
    kb = InlineKeyboardBuilder()
    for ev in rows:
        subj = f"{ev.subject.name} · " if ev.subject else ""
        state = "" if ev.is_open else " (закрыта)"
        lines.append(f"#{ev.id} · {subj}{ev.title}{state}")
        kb.button(text=f"👁 {ev.title[:30]}", callback_data=f"pq:ev_view:{ev.id}")
    kb.button(text="➕ Новая очередь", callback_data="pq:ev_add")
    kb.button(text=texts.BTN_BACK, callback_data="p:queues")
    kb.adjust(1)
    await cb.message.answer("\n".join(lines), reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("pq:ev_view:"), IsAdmin())
async def ev_view(cb: CallbackQuery, session: AsyncSession, user: User):
    from bot.handlers.queues import _render_event

    ev_id = int(cb.data.split(":")[2])
    text, _ = await _render_event(session, ev_id, user.id)
    kb = InlineKeyboardBuilder()
    ev = await session.get(DefenseEvent, ev_id)
    kb.button(text="🔒 Закрыть" if ev.is_open else "🔓 Открыть",
              callback_data=f"pq:ev_toggle:{ev_id}")
    kb.button(text="➕ Добавить окошки", callback_data=f"pq:ev_slots:{ev_id}")
    kb.button(text="🗑 Удалить очередь", callback_data=f"pq:ev_del:{ev_id}")
    kb.adjust(1)
    await cb.message.answer(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("pq:ev_toggle:"), IsAdmin())
async def ev_toggle(cb: CallbackQuery, session: AsyncSession):
    ev = await session.get(DefenseEvent, int(cb.data.split(":")[2]))
    if ev:
        ev.is_open = not ev.is_open
        await session.commit()
    await cb.answer("Готово.")


@router.callback_query(F.data.startswith("pq:ev_del:"), IsAdmin())
async def ev_del(cb: CallbackQuery, session: AsyncSession):
    ev = await session.get(DefenseEvent, int(cb.data.split(":")[2]))
    if ev:
        await session.delete(ev)
        await session.commit()
        await cb.answer("Удалила очередь.")
        await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "pq:ev_add", IsAdmin())
async def ev_add(cb: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.set_state(NewDefense.subject)
    await cb.message.answer(
        "По какому предмету?",
        reply_markup=_subject_kb(await _subjects(session), "evsub").as_markup(),
    )
    await cb.answer()


@router.callback_query(NewDefense.subject, F.data.startswith("evsub:"))
async def ev_subject(cb: CallbackQuery, state: FSMContext):
    await state.update_data(subject_id=int(cb.data.split(":")[1]) or None)
    await state.set_state(NewDefense.title)
    await cb.message.answer("Название (например «Защита проектного практикума»):",
                            reply_markup=cancel_menu())
    await cb.answer()


@router.message(NewDefense.title, F.text)
async def ev_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(NewDefense.description)
    await message.answer("Описание/что подготовить. Или «-»:")


@router.message(NewDefense.description, F.text)
async def ev_desc(message: Message, state: FSMContext):
    desc = None if message.text.strip() == "-" else message.text.strip()
    await state.update_data(description=desc)
    await state.set_state(NewDefense.slots)
    await message.answer(
        "Пришли окошки — по строке на пару:\n\n"
        "<code>10.10 3 пара\n10.10 4 пара x2\n15.10 2 пара x3</code>\n\n"
        "<code>x2</code> — сколько человек можно на эту пару."
    )


@router.message(NewDefense.slots, F.text)
async def ev_slots(message: Message, state: FSMContext, session: AsyncSession, user: User):
    parsed, bad = queues.parse_slot_lines(message.text)
    if bad:
        await message.answer("Не разобрала строки:\n" + "\n".join(bad[:8]))
        return
    if not parsed:
        await message.answer("Пусто. Пришли окошки.")
        return
    data = await state.get_data()
    ev = DefenseEvent(
        subject_id=data["subject_id"], title=data["title"],
        description=data["description"], created_by=user.id,
    )
    session.add(ev)
    await session.flush()
    n = await queues.create_slots(session, ev, parsed)
    await state.clear()
    await message.answer(f"Создала очередь: {n} окошек.", reply_markup=main_menu(True))


@router.callback_query(F.data.startswith("pq:ev_slots:"), IsAdmin())
async def ev_more_slots(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AddSlots.waiting)
    await state.update_data(event_id=int(cb.data.split(":")[2]))
    await cb.message.answer(
        "Пришли новые окошки:\n<code>20.10 3 пара x2</code>", reply_markup=cancel_menu()
    )
    await cb.answer()


@router.message(AddSlots.waiting, F.text)
async def add_slots_apply(message: Message, state: FSMContext, session: AsyncSession, bot: Bot):
    parsed, bad = queues.parse_slot_lines(message.text)
    if bad or not parsed:
        await message.answer("Не разобрала. Формат: <code>20.10 3 пара x2</code>")
        return
    data = await state.get_data()
    ev = await session.get(DefenseEvent, data["event_id"])
    n = await queues.create_slots(session, ev, parsed)
    await state.clear()
    await message.answer(f"Добавила {n} окошек.", reply_markup=main_menu(True))
    settings = get_settings()
    if settings.supergroup_id:
        with_ = ", ".join(f"{p['date'].strftime('%d.%m')} ({p['pair']} пара)" for p in parsed)
        await bot.send_message(
            settings.supergroup_id,
            f"🎓 В очереди «{ev.title}» новые окошки: {with_}. Записывайтесь — «🎓 Сдачи».",
        )
