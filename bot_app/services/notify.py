"""Единая точка доставки «аккаунту N» (plans/multitenancy_gaps_2026_08_06.md §5.5/§3.13).

Раньше всё, что «уведомить», было зашито на владельца (`push_chat_id()`, `tg.get_owner()`,
старый `scheduler.py`) — friend-аккаунты не получали ничего. `notify_account` резолвит
получателя по `account_id` и шлёт через его **primary** `accounts.telegram_chat_id` — тот
же принцип, что уже в `bot_app.config.push_chat_id()` (primary/DB-owner приоритетнее,
без фан-аута на secondary Telegram-identity, чтобы не задублировать сообщение на оба
устройства одного человека).

`broadcast_to_active_accounts` — цикл по всем активным аккаунтам поверх того же примитива,
для будущих рассылок (дайджест/discovery и т.п.). Дайджест и discovery-прогрев product-но
выключены (см. докстринг `scheduler.py`) — этот модуль только заводит примитив доставки,
сам не регистрирует ни одного cron. Активировать рассылку позже — значит вызвать
`broadcast_to_active_accounts` из нового `register_handler`/`add_cron` в `scheduler.py`,
не изобретать доставку заново в каждом сервисе.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot
from aiogram.types import Message

from bot_app.telegram_send import safe_send
from core.platform.repo.accounts import AccountRecord, get_account_by_id, list_active_accounts

logger = logging.getLogger(__name__)


async def notify_account(
    bot: Bot,
    account_id: int,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    reply_markup: Any = None,
    disable_web_page_preview: bool = True,
) -> Message | None:
    """Отправить текст аккаунту в его primary Telegram-чат.

    `None` — аккаунт не найден/не активен/ещё не привязал Telegram (нет `telegram_chat_id`).
    Это ожидаемо (self-serve друг мог зайти только через веб) и не логируется выше debug.
    """
    account = await get_account_by_id(account_id)
    if account is None or account.status != "active" or account.telegram_chat_id is None:
        logger.debug(
            "notify_account: нет доставки account_id=%s (нет привязанного чата или не активен)",
            account_id,
        )
        return None
    return await safe_send(
        bot,
        int(account.telegram_chat_id),
        text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview,
    )


async def broadcast_to_active_accounts(
    bot: Bot,
    build_message: Callable[[AccountRecord], Awaitable[str | None]],
) -> dict[str, int]:
    """Разослать активным аккаунтам (owner ∪ member) текст, собранный для каждого отдельно.

    `build_message(account)` возвращает `None` → аккаунт молча пропускается (типично: у него
    нет данных для этой рассылки — пустой дайджест и т.п.). Не вызывается пока ни из одного
    cron (см. докстринг модуля) — сборка на будущее, а не активная рассылка сегодня.
    """
    accounts = await list_active_accounts()
    sent = 0
    skipped = 0
    for account in accounts:
        text = await build_message(account)
        if text is None:
            skipped += 1
            continue
        delivered = await notify_account(bot, account.id, text)
        if delivered is not None:
            sent += 1
        else:
            skipped += 1
    return {"total": len(accounts), "sent": sent, "skipped": skipped}


__all__ = ["broadcast_to_active_accounts", "notify_account"]
