"""Калибровка зарплат: захват постов с вилкой → очередь → авто-разбор (always-on).

UI (команда `/calib on/off/status/flush`, кнопки меню) удалён: режим больше не нужно
включать руками — бот молча собирает вилки из любого пересланного поста с зарплатной
вилкой, разбор запускается сам по debounce. Пользователь ничего не настраивает.
Backend-free: очередь/сэмплы — `core.domains.market.salary_calib`;
извлечение/отчёты — `core.domains.market.salary_calibration`.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot_app.access import resolve_account
from bot_app.config import get_bot_settings
from bot_app.filters import IsAccount, IsForwarded
from bot_app.services import salary_calib_pipeline as pipeline
from bot_app.services.salary_calib_orchestrator import salary_calib_orchestrator

logger = logging.getLogger(__name__)
router = Router(name="salary_calibration")


def _forward_channel_label(message: Message) -> str:
    if message.forward_from_chat and message.forward_from_chat.title:
        return str(message.forward_from_chat.title)
    if message.forward_sender_name:
        return str(message.forward_sender_name)
    return ""


def _message_text(message: Message) -> str:
    return (message.text or message.caption or "").strip()


@router.message(
    IsAccount(),
    F.chat.type == ChatType.PRIVATE,
    F.text | F.caption,
)
async def handle_salary_post(message: Message, bot: Bot) -> None:
    """Любой входящий текст/форвард → если похоже на пост с вилкой, в очередь калибровки.

    Always-on: не проверяем ручной режим. Не-вилочные тексты `enqueue_if_salary_post`
    отсеивает сам (возвращает accepted=False) — дальше сообщение уйдёт в HR/прочие
    хендлеры ниже по роутеру.
    """
    text = _message_text(message)
    if not text or text.startswith("/"):
        return

    account = await resolve_account(user_id=message.from_user.id) if message.from_user else None
    if account is None:
        return

    channel = _forward_channel_label(message) if await IsForwarded()(message) else ""
    accepted, qid = await pipeline.enqueue_if_salary_post(
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=text,
        account_id=account.id,
        forward_channel=channel,
    )

    if not accepted:
        return

    logger.info("Salary calib enqueued id=%s chat=%s", qid, message.chat.id)

    if not get_bot_settings().salary_calib_auto:
        return

    salary_calib_orchestrator.attach(bot)
    await salary_calib_orchestrator.on_post_enqueued(message.chat.id)
