"""ИИ-ассистент: свободный вопрос в личке → ответ по базе знаний, либо эскалация старосте."""

from __future__ import annotations

import logging
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
router.message.filter(IsRegistered())
log = logging.getLogger(__name__)

_last_calls: dict[int, list[float]] = defaultdict(list)


def _rate_ok(user_id: int, limit: int) -> bool:
    now = time.time()
    calls = [t for t in _last_calls[user_id] if now - t < 3600]
    _last_calls[user_id] = calls
    if len(calls) >= limit:
        return False
    calls.append(now)
    return True


@router.message(F.text.casefold() == texts.BTN_ASK.casefold())
@router.message(Command("ask"))
async def ask_prompt(message: Message):
    await message.answer(texts.AI_ASK)


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
)
async def free_question(
    message: Message, session: AsyncSession, ai: AiClient, user: User, bot: Bot
):
    q = message.text.strip()
    if len(q) < 4:
        return

    if not ai.enabled:
        await message.answer(texts.AI_DISABLED)
        return

    settings = get_settings()
    if not _rate_ok(user.id, settings.ai_user_hourly_limit):
        await message.answer(texts.AI_RATE_LIMITED)
        return

    thinking = await message.answer(texts.AI_THINKING)
    try:
        entries = await relevant_entries(session, q)
        kb_block = render_kb_block(entries)
        res = await ai.complete(
            session=session,
            system=ASSISTANT_SYSTEM,
            user_content=f"{kb_block}\n\nВОПРОС СТУДЕНТА: {q}",
            kind="assistant",
            user_id=user.id,
            max_tokens=600,
            question_for_log=q,
        )
    except BudgetExceeded:
        await thinking.edit_text(texts.AI_BUDGET_EXCEEDED)
        return
    except Exception:  # noqa: BLE001
        log.exception("assistant call failed")
        await thinking.edit_text(texts.SOMETHING_WRONG)
        return

    answer = res.text.strip()
    low_conf = (not answer) or any(
        p in answer.lower() for p in ["нет точных данных", "нет информации", "не знаю", "переслать вопрос"]
    )
    kb = InlineKeyboardBuilder()
    kb.button(text="📨 Переслать вопрос старосте", callback_data="ai:escalate")
    await thinking.edit_text(
        answer or texts.AI_DONT_KNOW,
        reply_markup=kb.as_markup() if low_conf else None,
    )
    # временно кладём вопрос для возможной эскалации
    _pending[user.id] = q


_pending: dict[int, str] = {}


@router.callback_query(F.data == "ai:escalate")
async def escalate(cb: CallbackQuery, session: AsyncSession, user: User, bot: Bot):
    q = _pending.get(user.id)
    if not q:
        await cb.answer("Вопрос не найден, задай заново.", show_alert=True)
        return
    eq = EscalatedQuestion(user_id=user.id, question=q)
    session.add(eq)
    await session.commit()
    settings = get_settings()
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"❓ Вопрос от {user.full_name} (@{user.username or '—'}):\n\n{q}\n\n"
                f"Ответь командой: <code>/answer {eq.id} твой ответ</code>",
            )
        except Exception:  # noqa: BLE001
            pass
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.message.answer(texts.AI_ESCALATED)
    await cb.answer()


@router.message(Command("answer"))
async def answer_escalated(message: Message, session: AsyncSession, user: User, bot: Bot):
    if not user or not user.is_admin:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: /answer <id> <текст ответа>")
        return
    eq = await session.get(EscalatedQuestion, int(parts[1]))
    if eq is None:
        await message.answer("Вопрос не найден.")
        return
    eq.answer = parts[2]
    eq.answered_by = user.id
    eq.is_open = False
    await session.commit()
    target = await session.get(User, eq.user_id)
    if target:
        await bot.send_message(
            target.tg_id, f"Ответ старосты на твой вопрос:\n\n<i>{eq.question}</i>\n\n{parts[2]}"
        )
    await message.answer("Отправила студенту.")
