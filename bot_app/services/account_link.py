"""Кнопка «Добавить аккаунт» — привязка ЕЩЁ одного Telegram-id к уже существующему аккаунту.

Соискатели часто пишут HR-переписку с одного Telegram-аккаунта, а личным пользуются для
остального, хотя боту можно писать с любого — без этой кнопки второй Telegram-id при первом же
`/start` заводил бы ВТОРОЙ независимый `accounts`-ряд (member), плодя дубли. Пользователь
присылает токен, уже действующий у его другого аккаунта — бот распознаёт это как «у человека
несколько Telegram» и привязывает ТЕКУЩИЙ Telegram-id как secondary-identity
(`core.platform.repo.accounts.link_telegram_identity`), не создавая новый ряд.

Если у текущего Telegram-id уже есть СВОЙ отдельный `accounts`-ряд (например, случайно нажал
«Токен авторизации» до того, как узнал про эту кнопку) — тихо отвязываем и гасим его, но
ТОЛЬКО если в нём нет данных (`account_has_content`); если данные есть — отказываем понятным
сообщением и ничего не трогаем, дальше — вручную через администратора. `disable_account`
(`status='disabled'`) уже достаточно, чтобы закрыть старые сессии дубля: `web_auth`
фильтрует активные сессии по `accounts.status = 'active'`, отдельно гасить их не нужно.

Логика отделена от aiogram-хендлеров ради тестов без Telegram-моков (как и
`bot_app.services.auth_token`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from core.domains.profile.web_auth import find_account_by_raw_token
from core.platform.repo.accounts import (
    AccountRecord,
    account_has_content,
    disable_account,
    link_telegram_identity,
)

logger = logging.getLogger(__name__)

LinkReason = Literal["not_found", "already_linked", "conflict"]


@dataclass(frozen=True)
class LinkOutcome:
    """Результат попытки привязки: `ok` + при неудаче — машиночитаемая причина для хендлера."""

    ok: bool
    account: AccountRecord | None = None
    reason: LinkReason | None = None


async def link_telegram_account(
    *,
    raw_token: str,
    user_id: int,
    chat_id: int,
    username: str | None,
) -> LinkOutcome:
    """Привязать `user_id` (текущий Telegram-чат) как secondary-identity аккаунта,
    которому принадлежит `raw_token`."""
    from bot_app.access import invalidate, resolve_account

    target = await find_account_by_raw_token(raw_token)
    if target is None:
        return LinkOutcome(ok=False, reason="not_found")

    current = await resolve_account(user_id=user_id)
    if current is not None and current.id == target.id:
        return LinkOutcome(ok=False, reason="already_linked", account=target)

    if current is not None and current.id != target.id:
        if await account_has_content(current.id):
            logger.warning(
                "account_link: конфликт — user_id=%s уже привязан к account_id=%s с данными, "
                "привязка к account_id=%s отклонена (нужен ручной разбор администратора)",
                user_id,
                current.id,
                target.id,
            )
            return LinkOutcome(ok=False, reason="conflict", account=current)
        await disable_account(current.id)
        logger.info(
            "account_link: пустой дубль account_id=%s (user_id=%s) отвязан перед слиянием",
            current.id,
            user_id,
        )

    await link_telegram_identity(
        account_id=target.id,
        telegram_user_id=user_id,
        telegram_username=(username.lstrip("@") if username else None) or None,
        telegram_chat_id=chat_id,
    )
    invalidate()
    logger.info("account_link: user_id=%s привязан к account_id=%s", user_id, target.id)
    return LinkOutcome(ok=True, account=target)


__all__ = ["LinkOutcome", "link_telegram_account"]
