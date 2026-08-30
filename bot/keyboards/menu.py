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
    kb.row(KeyboardButton(text=texts.BTN_GROUP), KeyboardButton(text=texts.BTN_FAQ))
    kb.row(KeyboardButton(text=texts.BTN_FUN))
    if is_admin:
        kb.row(KeyboardButton(text=texts.BTN_ADMIN))
    return kb.as_markup(resize_keyboard=True)


def cancel_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.row(KeyboardButton(text=texts.BTN_CANCEL))
    return kb.as_markup(resize_keyboard=True)


def panel_home() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📣 Написать всем", callback_data="p:broadcast")
    kb.button(text="📅 Расписание", callback_data="p:sched")
    kb.button(text="📚 Подтвердить ДЗ", callback_data="p:hw")
    kb.button(text="🎓 База знаний", callback_data="p:kb")
    kb.button(text="👥 Список группы", callback_data="p:roster")
    kb.button(text="🎂 Дни рождения", callback_data="p:bdays")
    kb.button(text="🎉 Праздники", callback_data="p:holidays")
    kb.button(text="🖼 Картинки (ДР / мемы)", callback_data="p:media")
    kb.button(text="🔗 Привязать тему к предмету", callback_data="p:topic_help")
    kb.button(text="🛠 Настройка", callback_data="p:setup")
    kb.adjust(1)
    return kb.as_markup()


def panel_sched() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Загрузить расписание", callback_data="p:sched_import")
    kb.button(text="📤 Опубликовать в чат группы", callback_data="p:sched_post")
    kb.button(text=texts.BTN_BACK, callback_data="p:home")
    kb.adjust(1)
    return kb.as_markup()


def panel_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔄 Обновить с сайта вуза", callback_data="p:kb_refresh")
    kb.button(text="➕ Добавить запись вручную", callback_data="p:kb_add")
    kb.button(text="🧩 Дополнить преподавателя", callback_data="p:kb_enrich")
    kb.button(text="📋 Все записи / удалить", callback_data="p:kb_list")
    kb.button(text=texts.BTN_BACK, callback_data="p:home")
    kb.adjust(1)
    return kb.as_markup()


def panel_setup() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🤖 Проверить ИИ", callback_data="p:ai_test")
    kb.button(text="🧪 Заполнить демо-данными", callback_data="p:seed")
    kb.button(text="🧹 Очистить демо-данные", callback_data="p:wipe")
    kb.button(text=texts.BTN_BACK, callback_data="p:home")
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
