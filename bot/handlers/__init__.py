"""Сборка всех роутеров в один. Порядок важен: сначала команды и меню, потом FSM-разделы."""

from __future__ import annotations

from aiogram import Router

from bot.handlers import (
    admin,
    assistant,
    common,
    faq,
    homework,
    kb_admin,
    reminders,
    schedule,
    stubs,
)


def build_router() -> Router:
    root = Router(name="root")
    root.include_router(common.router)
    root.include_router(schedule.router)
    root.include_router(reminders.router)
    root.include_router(homework.router)
    root.include_router(faq.router)
    root.include_router(kb_admin.router)
    root.include_router(admin.router)
    root.include_router(stubs.router)
    # assistant — последним: ловит любой свободный текст в личке как вопрос к ИИ
    root.include_router(assistant.router)
    return root
