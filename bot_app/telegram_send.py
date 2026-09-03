"""Безопасная отправка сообщений с retry при flood control (порт `bot.utils.telegram_send`, S10).

`safe_reply`/`safe_send`/`safe_send_photo` ждут при `TelegramRetryAfter`;
`send_typing` — индикатор «печатает».
Опциональный `track_kind=` пишет исходящее в `tg_ui_messages` (best-effort).
HTML-экранирование — `bot_app.utils.esc`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile, Message

logger = logging.getLogger(__name__)


async def send_typing(message: Message) -> None:
    bot = message.bot
    if bot is None:
        return
    try:
        await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception as exc:  # noqa: BLE001 — индикатор не критичен
        logger.debug("send_typing failed: %s", exc)


async def _maybe_track(
    chat_id: int,
    sent: Message | None,
    track_kind: str | None,
    *,
    vacancy_id: str | None,
    ttl: timedelta | float | int | None,
) -> None:
    if sent is None or not track_kind:
        return
    from bot_app.storage.message_registry import track

    await track(
        chat_id,
        sent.message_id,
        track_kind,
        vacancy_id=vacancy_id,
        ttl=ttl,
    )


async def safe_send(
    bot: Bot,
    chat_id: int,
    text: str,
    *,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
    reply_markup: Any = None,
    max_retries: int = 3,
    track_kind: str | None = None,
    vacancy_id: str | None = None,
    ttl: timedelta | float | int | None = None,
) -> Message | None:
    """send_message с retry при flood control; опционально track в tg_ui_messages."""
    sent: Message | None = None
    for attempt in range(max_retries):
        try:
            sent = await bot.send_message(
                chat_id,
                text,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
            break
        except TelegramRetryAfter as exc:
            wait = exc.retry_after + 1
            logger.warning(
                "Flood control, жду %ss (попытка %d/%d, chat=%s)",
                wait,
                attempt + 1,
                max_retries,
                chat_id,
            )
            if attempt + 1 >= max_retries:
                raise
            await asyncio.sleep(wait)
    await _maybe_track(chat_id, sent, track_kind, vacancy_id=vacancy_id, ttl=ttl)
    return sent


async def safe_send_photo(
    bot: Bot,
    chat_id: int,
    photo: bytes,
    *,
    caption: str | None = None,
    reply_to_message_id: int | None = None,
    parse_mode: str | None = None,
    reply_markup: Any = None,
    filename: str = "score_card.png",
    max_retries: int = 3,
    track_kind: str | None = None,
    vacancy_id: str | None = None,
    ttl: timedelta | float | int | None = None,
) -> Message | None:
    """send_photo с retry при flood control; опционально track в tg_ui_messages."""
    sent: Message | None = None
    for attempt in range(max_retries):
        try:
            sent = await bot.send_photo(
                chat_id,
                BufferedInputFile(photo, filename=filename),
                caption=caption,
                reply_to_message_id=reply_to_message_id,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            break
        except TelegramRetryAfter as exc:
            wait = exc.retry_after + 1
            logger.warning(
                "Flood control (photo), жду %ss (попытка %d/%d, chat=%s)",
                wait,
                attempt + 1,
                max_retries,
                chat_id,
            )
            if attempt + 1 >= max_retries:
                raise
            await asyncio.sleep(wait)
    await _maybe_track(chat_id, sent, track_kind, vacancy_id=vacancy_id, ttl=ttl)
    return sent


async def safe_reply(
    message: Message,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = False,
    reply_markup: Any = None,
    max_retries: int = 3,
    track_kind: str | None = None,
    vacancy_id: str | None = None,
    ttl: timedelta | float | int | None = None,
) -> Message | None:
    """reply() с автоматическим ожиданием при TelegramRetryAfter.

    parse_mode по умолчанию HTML: prep/debrief-карточки собираются HTML-разметкой (esc на
    пользовательских строках).
    """
    sent: Message | None = None
    for attempt in range(max_retries):
        try:
            sent = await message.reply(
                text,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup,
            )
            break
        except TelegramRetryAfter as exc:
            wait = exc.retry_after + 1
            logger.warning(
                "Flood control, жду %ss (попытка %d/%d, chat=%s)",
                wait,
                attempt + 1,
                max_retries,
                message.chat.id,
            )
            if attempt + 1 >= max_retries:
                raise
            await asyncio.sleep(wait)
    await _maybe_track(
        message.chat.id,
        sent,
        track_kind,
        vacancy_id=vacancy_id,
        ttl=ttl,
    )
    return sent
