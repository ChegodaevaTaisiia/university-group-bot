"""Студент: разбор тем и запись в очередь на защиту/выступление."""

from __future__ import annotations

from datetime import UTC

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot import texts
from bot.db.models import (
    DefenseEvent,
    DefenseSlot,
    TopicItem,
    TopicList,
    User,
)
from bot.filters import IsRegistered
from bot.services import queues

router = Router(name="queues")
router.message.filter(IsRegistered())


@router.message(F.text.casefold() == texts.BTN_QUEUES.casefold())
@router.message(Command("queues"))
async def root(message: Message, session: AsyncSession):
    lists = list(
        await session.scalars(
            select(TopicList).options(selectinload(TopicList.subject))
            .where(TopicList.is_open.is_(True))
        )
    )
    events = list(
        await session.scalars(
            select(DefenseEvent).options(selectinload(DefenseEvent.subject))
            .where(DefenseEvent.is_open.is_(True))
        )
    )
    if not lists and not events:
        await message.answer("Пока нет ни списков тем, ни очередей на защиту.")
        return
    kb = InlineKeyboardBuilder()
    for lst in lists:
        free, total = await queues.free_topics_count(session, lst)
        subj = f"{lst.subject.name} · " if lst.subject else ""
        kb.button(text=f"📝 {subj}{lst.title} ({free}/{total} свободно)",
                  callback_data=f"q:list:{lst.id}")
    for ev in events:
        subj = f"{ev.subject.name} · " if ev.subject else ""
        kb.button(text=f"🎓 {subj}{ev.title}", callback_data=f"q:ev:{ev.id}")
    kb.button(text="📌 Мои темы и защиты", callback_data="q:mine")
    kb.adjust(1)
    await message.answer("🎓 <b>Сдачи</b>\nВыбери список тем или очередь:",
                         reply_markup=kb.as_markup())


# ─────────────────────────── темы ──────────────────────────────────────


def _topic_kb(lst_id: int, items: list[TopicItem], me: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for it in items:
        if it.taken_by is None:
            kb.button(text=f"✅ Взять: {it.text[:45]}", callback_data=f"q:take:{it.id}")
        elif it.taken_by == me:
            kb.button(text=f"↩️ Освободить: {it.text[:40]}", callback_data=f"q:drop:{it.id}")
    kb.adjust(1)
    return kb


async def _render_list(session: AsyncSession, lst_id: int) -> tuple[str, list[TopicItem]]:
    lst = await session.get(TopicList, lst_id)
    items = list(
        await session.scalars(
            select(TopicItem).options(selectinload(TopicItem.student))
            .where(TopicItem.list_id == lst_id).order_by(TopicItem.position)
        )
    )
    lines = [f"📝 <b>{lst.title}</b>"]
    if lst.deadline:
        lines.append(f"Срок: {lst.deadline.strftime('%d.%m')}")
    lines.append("")
    for it in items:
        who = f" — <i>{it.student.full_name}</i>" if it.student else " — <b>свободно</b>"
        lines.append(f"{it.position}. {it.text}{who}")
    return "\n".join(lines), items


@router.callback_query(F.data.startswith("q:list:"))
async def show_list(cb: CallbackQuery, session: AsyncSession, user: User):
    lst_id = int(cb.data.split(":")[2])
    text, items = await _render_list(session, lst_id)
    await cb.message.answer(text, reply_markup=_topic_kb(lst_id, items, user.id).as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("q:take:"))
async def take_topic(cb: CallbackQuery, session: AsyncSession, user: User):
    from datetime import datetime

    item = await session.get(TopicItem, int(cb.data.split(":")[2]))
    if item is None or item.taken_by is not None:
        await cb.answer("Эту тему уже разобрали.", show_alert=True)
    else:
        # не даём брать вторую тему из того же списка
        mine = await session.scalar(
            select(TopicItem).where(
                TopicItem.list_id == item.list_id, TopicItem.taken_by == user.id
            )
        )
        if mine:
            await cb.answer(f"У тебя уже есть тема: {mine.text[:60]}", show_alert=True)
            return
        item.taken_by = user.id
        item.taken_at = datetime.now(UTC)
        await session.commit()
        await cb.answer("Тема закреплена за тобой ✅")
    text, items = await _render_list(session, item.list_id)
    await cb.message.edit_text(text, reply_markup=_topic_kb(item.list_id, items, user.id).as_markup())


@router.callback_query(F.data.startswith("q:drop:"))
async def drop_topic(cb: CallbackQuery, session: AsyncSession, user: User):
    item = await session.get(TopicItem, int(cb.data.split(":")[2]))
    if item and item.taken_by == user.id:
        item.taken_by = None
        item.taken_at = None
        await session.commit()
        await cb.answer("Освободила тему.")
        text, items = await _render_list(session, item.list_id)
        await cb.message.edit_text(
            text, reply_markup=_topic_kb(item.list_id, items, user.id).as_markup()
        )
    else:
        await cb.answer()


# ─────────────────────── очередь на защиту ─────────────────────────────


async def _render_event(session: AsyncSession, ev_id: int, me: int):
    ev = await session.get(DefenseEvent, ev_id)
    slots = list(
        await session.scalars(
            select(DefenseSlot).options(selectinload(DefenseSlot.student))
            .where(DefenseSlot.event_id == ev_id)
            .order_by(DefenseSlot.on_date, DefenseSlot.pair_no, DefenseSlot.position)
        )
    )
    lines = [f"🎓 <b>{ev.title}</b>"]
    if ev.description:
        lines.append(ev.description)
    lines.append("")
    kb = InlineKeyboardBuilder()
    my_slot = next((s for s in slots if s.user_id == me and not s.is_reserve), None)
    grouped: dict = {}
    for s in slots:
        if s.is_reserve:
            continue
        grouped.setdefault((s.on_date, s.pair_no, s.at_time), []).append(s)
    for (d, pair, at), group in grouped.items():
        t = f" {at.strftime('%H:%M')}" if at else ""
        taken = [g for g in group if g.user_id]
        names = ", ".join(g.student.full_name for g in taken) or "—"
        lines.append(
            f"📅 {d.strftime('%d.%m')}, {pair} пара{t}: {len(taken)}/{len(group)} · {names}"
        )
        free = next((g for g in group if g.user_id is None), None)
        if free and my_slot is None:
            kb.button(
                text=f"✅ Записаться: {d.strftime('%d.%m')}, {pair} пара",
                callback_data=f"q:book:{free.id}",
            )
    if my_slot:
        kb.button(text="↩️ Отменить мою запись", callback_data=f"q:unbook:{my_slot.id}")
    reserves = [s for s in slots if s.is_reserve]
    if reserves:
        lines.append("\n<b>Запас:</b> " + ", ".join(
            s.student.full_name for s in reserves if s.student
        ))
    if not my_slot and not any(s.is_reserve and s.user_id == me for s in slots):
        kb.button(text="🔁 Записаться в запас", callback_data=f"q:reserve:{ev_id}")
    kb.adjust(1)
    return "\n".join(lines), kb


@router.callback_query(F.data.startswith("q:ev:"))
async def show_event(cb: CallbackQuery, session: AsyncSession, user: User):
    ev_id = int(cb.data.split(":")[2])
    text, kb = await _render_event(session, ev_id, user.id)
    await cb.message.answer(text, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("q:book:"))
async def book(cb: CallbackQuery, session: AsyncSession, user: User):
    slot = await session.get(DefenseSlot, int(cb.data.split(":")[2]))
    if slot is None or slot.user_id is not None:
        await cb.answer("Это окошко уже заняли.", show_alert=True)
    else:
        await queues.book_slot(session, slot, user.id)
        await cb.answer("Записал! Напоминание придёт заранее ⏰", show_alert=True)
    text, kb = await _render_event(session, slot.event_id, user.id)
    await cb.message.edit_text(text, reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("q:unbook:"))
async def unbook(cb: CallbackQuery, session: AsyncSession, user: User):
    slot = await session.get(DefenseSlot, int(cb.data.split(":")[2]))
    if slot and slot.user_id == user.id:
        ev_id = slot.event_id
        await queues.unbook_slot(session, slot)
        await cb.answer("Запись отменена.")
        text, kb = await _render_event(session, ev_id, user.id)
        await cb.message.edit_text(text, reply_markup=kb.as_markup())
    else:
        await cb.answer()


@router.callback_query(F.data.startswith("q:reserve:"))
async def reserve(cb: CallbackQuery, session: AsyncSession, user: User):
    ev = await session.get(DefenseEvent, int(cb.data.split(":")[2]))
    ok = await queues.add_reserve(session, ev, user.id)
    await cb.answer("Записал в запас — позову, если освободится окошко."
                    if ok else "Ты уже в запасе.", show_alert=True)
    text, kb = await _render_event(session, ev.id, user.id)
    await cb.message.edit_text(text, reply_markup=kb.as_markup())


# ─────────────────────── мои темы и защиты ────────────────────────────


@router.callback_query(F.data == "q:mine")
async def mine(cb: CallbackQuery, session: AsyncSession, user: User):
    topics = list(
        await session.scalars(
            select(TopicItem).options(selectinload(TopicItem.topic_list))
            .where(TopicItem.taken_by == user.id)
        )
    )
    slots = list(
        await session.scalars(
            select(DefenseSlot).options(selectinload(DefenseSlot.event))
            .where(DefenseSlot.user_id == user.id)
        )
    )
    lines = ["📌 <b>Мои темы и защиты</b>", ""]
    for t in topics:
        lines.append(f"📝 {t.topic_list.title}: {t.text}")
    for s in slots:
        if s.is_reserve:
            lines.append(f"🔁 {s.event.title} — в запасе")
        else:
            lines.append(f"🎓 {s.event.title} — {s.on_date.strftime('%d.%m')}, {s.pair_no} пара")
    if len(lines) == 2:
        lines.append("Пока ничего не выбрано.")
    await cb.message.answer("\n".join(lines))
    await cb.answer()
