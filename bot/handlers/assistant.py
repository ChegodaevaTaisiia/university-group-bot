"""ИИ-ассистент: вопрос в личке или обращение по имени в чате → ответ по базе знаний."""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict

from aiogram import Bot, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot import texts
from bot.config import get_settings
from bot.db.models import EscalatedQuestion, User
from bot.filters import IsRegistered
from bot.services.ai.client import AiClient, BudgetExceeded
from bot.services.ai.knowledge import relevant_entries, render_kb_block
from bot.services.ai.prompts import ASSISTANT_SYSTEM

router = Router(name="assistant")
log = logging.getLogger(__name__)

_last_calls: dict[int, list[float]] = defaultdict(list)
_pending: dict[int, str] = {}

_LOW_CONF = ("нет точных данных", "нет информации", "не знаю", "переслать вопрос")


def _rate_ok(user_id: int, limit: int) -> bool:
    now = time.time()
    calls = [t for t in _last_calls[user_id] if now - t < 3600]
    _last_calls[user_id] = calls
    if len(calls) >= limit:
        return False
    calls.append(now)
    return True


async def answer_question(
    message: Message, session: AsyncSession, ai: AiClient, question: str, user_id: int | None
) -> None:
    if not ai.enabled:
        await message.reply(texts.AI_DISABLED)
        return
    settings = get_settings()
    if user_id and not _rate_ok(user_id, settings.ai_user_hourly_limit):
        await message.reply(texts.AI_RATE_LIMITED)
        return

    thinking = await message.reply(texts.AI_THINKING)
    try:
        entries = await relevant_entries(session, question)
        res = await ai.complete(
            session=session,
            system=ASSISTANT_SYSTEM,
            user_content=f"{render_kb_block(entries)}\n\nВОПРОС СТУДЕНТА: {question}",
            kind="assistant",
            user_id=user_id,
            max_tokens=600,
            question_for_log=question,
        )
    except BudgetExceeded:
        await thinking.edit_text(texts.AI_BUDGET_EXCEEDED)
        return
    except Exception:  # noqa: BLE001
        log.exception("assistant call failed")
        await thinking.edit_text(texts.SOMETHING_WRONG)
        return

    answer = res.text.strip()
    low_conf = (not answer) or any(p in answer.lower() for p in _LOW_CONF)
    kb = None
    if low_conf and message.chat.type == "private" and user_id:
        b = InlineKeyboardBuilder()
        b.button(text="📨 Переслать вопрос старосте", callback_data="ai:escalate")
        kb = b.as_markup()
        _pending[user_id] = question
    await thinking.edit_text(answer or texts.AI_DONT_KNOW, reply_markup=kb)


# ─────────────────────────── личка ──────────────────────────────────────


@router.message(IsRegistered(), F.text.casefold() == texts.BTN_ASK.casefold())
@router.message(IsRegistered(), Command("ask"))
async def ask_prompt(message: Message):
    await message.answer(texts.AI_ASK)


@router.message(
    IsRegistered(),
    StateFilter(None),
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
)
async def free_question(message: Message, session: AsyncSession, ai: AiClient, user: User):
    q = message.text.strip()
    if len(q) >= 4:
        await answer_question(message, session, ai, q, user.id)


# ──────────────── обращение по имени в групповом чате ───────────────────

_NICK_RE_CACHE: dict[str, re.Pattern] = {}


def _nick_pattern(nick: str) -> re.Pattern:
    if nick not in _NICK_RE_CACHE:
        _NICK_RE_CACHE[nick] = re.compile(
            rf"^\s*{re.escape(nick)}[\s,!:—-]+(.+)", re.IGNORECASE | re.DOTALL
        )
    return _NICK_RE_CACHE[nick]


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text)
async def nickname_wake(message: Message, session: AsyncSession, ai: AiClient, user: User | None):
    m = _nick_pattern(get_settings().bot_nickname).match(message.text)
    if not m:
        return
    question = m.group(1).strip()
    if len(question) < 3:
        await message.reply(texts.AI_ASK)
        return
    await answer_question(message, session, ai, question, user.id if user else None)


# ─────────────────────────── эскалация ─────────────────────────────────


@router.callback_query(F.data == "ai:escalate")
async def escalate(cb: CallbackQuery, session: AsyncSession, user: User, bot: Bot):
    q = _pending.get(user.id)
    if not q:
        await cb.answer("Вопрос не найден, задай заново.", show_alert=True)
        return
    eq = EscalatedQuestion(user_id=user.id, question=q)
    session.add(eq)
    await session.commit()
    for admin_id in get_settings().admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"❓ Вопрос от {user.full_name} (@{user.username or '—'}):\n\n{q}\n\n"
                f"Ответить: <code>/reply {eq.id} твой ответ</code>",
            )
        except Exception:  # noqa: BLE001
            pass
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.AI_ESCALATED)
    await cb.answer()


@router.message(Command("reply"))
async def answer_escalated(message: Message, session: AsyncSession, user: User | None, bot: Bot):
    if not user or not user.is_admin:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: /reply <номер вопроса> <текст ответа>")
        return
    eq = await session.get(EscalatedQuestion, int(parts[1]))
    if eq is None:
        await message.answer("Вопрос не найден.")
        return
    eq.answer, eq.answered_by, eq.is_open = parts[2], user.id, False
    await session.commit()
    target = await session.get(User, eq.user_id)
    if target and target.tg_id:
        await bot.send_message(
            target.tg_id, f"Ответ старосты на твой вопрос:\n\n<i>{eq.question}</i>\n\n{parts[2]}"
        )
    await message.answer("Отправила студенту.")
