"""Узкие хелперы для aiogram-типов: InaccessibleMessage vs Message."""

from __future__ import annotations

from aiogram.types import Message


def editable_message(msg: object | None) -> Message | None:
    """Вернуть Message только если можно edit_text / edit_reply_markup."""
    return msg if isinstance(msg, Message) else None
