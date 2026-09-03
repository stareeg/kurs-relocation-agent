"""Уборка исходников батча пересылок сразу после сводки.

Продуктовый режим — всегда ``auto``: как только из пересылок извлечена полезная
информация и отправлена сводка, исходники удаляются. Режимы ``ask``/``off`` и
колбэки под старые сводки оставлены для обратной совместимости сообщений в чате.
Bot API: входящие в личке удаляются (<48ч); ошибки suppress.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_app.storage import batch_cleanup_pending
from core.config import current_account_id
from core.domains.profile.telegram_prefs import (
    BatchCleanupMode,
    get_telegram_prefs,
    set_telegram_prefs,
)
from core.platform.repo.accounts import resolve_default_account_id

logger = logging.getLogger(__name__)

# Callback'и сводки (ask). Меню after_score использует CB_CLEANUP_CHAT → тот же execute.
CB_BATCH_CLEANUP = "batch:cleanup"
CB_BATCH_CLEANUP_DONT_ASK = "batch:cleanup_dont_ask"


@dataclass(frozen=True)
class BatchCleanupPlan:
    """Что сделать с исходниками после отправки сводки."""

    mode: BatchCleanupMode
    message_ids: list[int]
    reply_markup: InlineKeyboardMarkup | None = None


def cleanup_ask_keyboard(n: int) -> InlineKeyboardMarkup:
    """Кнопки под сводкой в режиме ask."""
    count = max(0, int(n))
    label = f"Подчистить {count} пересланных" if count else "Подчистить пересланные"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=CB_BATCH_CLEANUP)],
            [
                InlineKeyboardButton(
                    text="Больше не спрашивать",
                    callback_data=CB_BATCH_CLEANUP_DONT_ASK,
                )
            ],
        ]
    )


async def plan_batch_cleanup(
    chat_id: int,
    message_ids: list[int],
    *,
    mode: BatchCleanupMode | None = None,
) -> BatchCleanupPlan:
    """Подготовить уборку. По умолчанию всегда auto (сразу после сводки).

    ``mode`` оставлен для тестов/явного override. Вызывать до ``safe_send`` сводки;
    сам delete — ``run_auto_cleanup`` после send.
    """
    ids = [int(m) for m in message_ids if m]
    # Селекты prefs убраны с UI — продуктово всегда подчищаем сразу.
    resolved: BatchCleanupMode = mode if mode is not None else "auto"

    if not ids or resolved == "off":
        batch_cleanup_pending.clear(chat_id)
        return BatchCleanupPlan(mode=resolved if ids else "off", message_ids=ids)

    if resolved == "auto":
        batch_cleanup_pending.clear(chat_id)
        return BatchCleanupPlan(mode="auto", message_ids=ids)

    batch_cleanup_pending.save(chat_id, ids)
    return BatchCleanupPlan(
        mode="ask",
        message_ids=ids,
        reply_markup=cleanup_ask_keyboard(len(ids)),
    )


async def run_auto_cleanup(bot: Bot, plan: BatchCleanupPlan, chat_id: int) -> int:
    """Если mode=auto — удалить исходники. Иначе 0."""
    if plan.mode != "auto" or not plan.message_ids:
        return 0
    return await delete_forward_messages(bot, chat_id, plan.message_ids)


async def delete_forward_messages(
    bot: Bot,
    chat_id: int,
    message_ids: list[int],
) -> int:
    """Удалить входящие форварды best-effort. Возвращает число успешных delete."""
    deleted = 0
    for mid in message_ids:
        try:
            await bot.delete_message(chat_id, mid)
            deleted += 1
        except Exception as exc:  # noqa: BLE001 — >48ч / нет прав / уже удалено
            logger.debug(
                "batch_cleanup delete_message failed chat=%s msg=%s: %s",
                chat_id,
                mid,
                exc,
            )
    return deleted


async def execute_pending_cleanup(bot: Bot, chat_id: int) -> int:
    """Pop pending message_id и удалить. 0 = нечего / пусто."""
    ids = batch_cleanup_pending.pop(chat_id)
    if not ids:
        return 0
    return await delete_forward_messages(bot, chat_id, ids)


async def set_batch_cleanup_auto() -> None:
    """Переключить prefs.batch_cleanup → auto («Больше не спрашивать»).

    M8 (plans/multitenancy_gaps_2026_08_06.md §3.13): всегда вызывается из callback-хендлера
    (`bot_app/handlers/menu.py`), то есть `current_account_id()` уже выставлен bot-middleware
    на вызывающего — раньше здесь падало прямо на владельца, и «Больше не спрашивать» друга
    молча переключало prefs владельца.
    """
    account_id = current_account_id() or await resolve_default_account_id()
    prefs = await get_telegram_prefs(account_id=account_id)
    if prefs.batch_cleanup == "auto":
        return
    await set_telegram_prefs(
        prefs.model_copy(update={"batch_cleanup": "auto"}), account_id=account_id
    )


__all__ = [
    "CB_BATCH_CLEANUP",
    "CB_BATCH_CLEANUP_DONT_ASK",
    "BatchCleanupPlan",
    "cleanup_ask_keyboard",
    "delete_forward_messages",
    "execute_pending_cleanup",
    "plan_batch_cleanup",
    "run_auto_cleanup",
    "set_batch_cleanup_auto",
]
