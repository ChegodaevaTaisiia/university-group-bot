"""Сборка всех роутеров в один. Порядок важен: сначала команды и меню, потом FSM-разделы."""

from __future__ import annotations

from aiogram import Router

from bot.handlers import (
    admin,
    assistant,
    common,
    faq,
    fun,
    group,
    homework,
    kb_admin,
    panel_extra,
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
    root.include_router(group.router)
    root.include_router(fun.router)
    root.include_router(kb_admin.router)
    root.include_router(panel_extra.router)
    root.include_router(admin.router)
    root.include_router(stubs.router)
    # assistant — последним: свободный текст в личке и обращение по имени в чате
    root.include_router(assistant.router)
    return root
