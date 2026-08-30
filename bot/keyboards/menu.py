"""Reply- и inline-клавиатуры общего назначения."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from bot import texts


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=texts.BTN_SCHEDULE), KeyboardButton(text=texts.BTN_HOMEWORK))
    kb.row(KeyboardButton(text=texts.BTN_REMINDERS), KeyboardButton(text=texts.BTN_ASK))
    kb.row(KeyboardButton(text=texts.BTN_FAQ))
    if is_admin:
        kb.row(KeyboardButton(text=texts.BTN_ADMIN))
    return kb.as_markup(resize_keyboard=True)


def cancel_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=texts.BTN_CANCEL))
    return kb.as_markup(resize_keyboard=True)


def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📣 Написать всем", callback_data="admin:broadcast")
    kb.button(text="📅 Расписание", callback_data="admin:schedule")
    kb.button(text="📚 Подтвердить ДЗ", callback_data="admin:hw")
    kb.button(text="🤖 База знаний", callback_data="admin:kb")
    kb.button(text="👥 Список группы", callback_data="admin:roster")
    kb.button(text="🧪 Проверить ИИ", callback_data="admin:ai_selftest")
    kb.adjust(1)
    return kb.as_markup()


def yes_no(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да", callback_data=f"{prefix}:yes"),
                InlineKeyboardButton(text="Нет", callback_data=f"{prefix}:no"),
            ]
        ]
    )
