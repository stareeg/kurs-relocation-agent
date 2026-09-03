"""Сборка inline-клавиатур «назад в меню» и снятие reply-клавиатуры.

Главное адаптивное меню — `bot_app.services.menu_manager`. Reply-клавиатура снизу
убрана: два меню = шум; для старых чатов — `remove_reply_keyboard()`.
Подписи без декоративных эмодзи. Подменю discovery/калибровки удалены вместе с этими
разделами из бота.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardRemove,
)


def remove_reply_keyboard() -> ReplyKeyboardRemove:
    """Снять персистентную reply-клавиатуру у клиента (после TB-3.5 её больше не шлём)."""
    return ReplyKeyboardRemove(remove_keyboard=True)


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню (для вторичных экранов)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="В меню", callback_data="menu:home")]]
    )


def with_back_button(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Добавить кнопку «В меню» в конец произвольного набора рядов."""
    full = list(rows)
    full.append([InlineKeyboardButton(text="В меню", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=full)
