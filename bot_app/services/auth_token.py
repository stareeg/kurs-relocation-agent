"""Кнопка «Токен авторизации» — выдача токена входа в веб из бота (Этап 5).

Сценарии:
- оператор (DB-owner ∪ env-allowlist) — выпуск/перевыпуск токена; аккаунт (`user_id`)
  сохраняется, старый токен не гаснет (несколько устройств, Part C);
- любой другой Telegram-пользователь — self-serve MEMBER-аккаунт на ЭТОЙ же инсталляции
  (Этап 5, план §5). Владельцем становится ТОЛЬКО совпадение с env-allowlist
  (`ADMIN_USER_ID`/`ADMIN_USER_IDS`) — единый продуктовый бот и общий VM-хостинг больше не
  предполагают bootstrap «первый нажавший становится владельцем»: `.env` всегда содержит id
  владельца заранее, случайное первое нажатие чужого пользователя не должно перехватывать роль.

Токен присылается отдельным сообщением и ТОЛЬКО сырым значением — чтобы его было удобно
скопировать одним тапом, без обрамляющего текста. Перевыпуск троттлится (`_REISSUE_COOLDOWN`):
частые повторные нажатия не должны плодить сессии и путать — новый токен нужен по сути только
для входа на новом устройстве (старые при этом остаются рабочими).

Логика отделена от aiogram-хендлеров ради тестов без Telegram-моков.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from core.domains.profile.web_auth import (
    get_last_issued_at,
    has_completed_web_login,
    issue_web_auth_token,
)
from core.platform.repo.accounts import upsert_account

logger = logging.getLogger(__name__)

# Минимальный интервал между перевыпусками токена для одного аккаунта.
_REISSUE_COOLDOWN = timedelta(hours=1)


@dataclass(frozen=True)
class AuthTokenReply:
    """Результат запроса токена: сырой токен (или None при cooldown) + флаги сценария."""

    token: str | None
    role: Literal["owner", "member"] = "owner"
    account_id: int | None = None
    cooldown_remaining: timedelta | None = None


async def _cooldown_remaining(account_id: int) -> timedelta | None:
    """Сколько ещё ждать до разрешённого перевыпуска; None — перевыпускать можно.

    Источник даты — `get_last_issued_at` (Part C: сессии, не колонка `accounts`); throttle не
    защищает единственный токен от гибели (сессии больше не гасят друг друга при перевыпуске),
    а просто не даёт частым нажатиям кнопки плодить сессии в списке устройств.
    """
    issued_at = await get_last_issued_at(account_id)
    if issued_at is None:
        return None
    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=UTC)
    remaining = (issued_at + _REISSUE_COOLDOWN) - datetime.now(UTC)
    return remaining if remaining.total_seconds() > 0 else None


async def issue_auth_token_reply(
    *,
    user_id: int,
    chat_id: int,
    username: str | None,
) -> AuthTokenReply:
    """Выдать токен входа: оператору или self-serve member-аккаунту.

    При повторном нажатии в пределах cooldown возвращает `token=None` и
    `cooldown_remaining` — хендлер отвечает коротким alert'ом, новый токен не плодится.
    Исключение: человек ещё ни разу не вошёл в веб (потерял сообщение бота) — перевыпускаем.
    """
    from bot_app.access import invalidate, is_allowed_admin, resolve_operator_account

    if await is_allowed_admin(user_id=user_id, username=username):
        account = await resolve_operator_account(
            user_id=user_id, username=username, chat_id=chat_id
        )
    else:
        # Владельцем становится только совпадение с env-allowlist (resolve_operator_account
        # выше) — здесь всегда member, независимо от того, привязан ли уже владелец инсталляции.
        account = await upsert_account(
            telegram_user_id=user_id,
            telegram_username=(username.lstrip("@") if username else None) or None,
            telegram_chat_id=chat_id,
            role="member",
        )
        invalidate()
        logger.info("web_auth: self-serve member-аккаунт user_id=%s", user_id)
        from core.domains.career.friendships_repo import ensure_system_admin_friendships

        await ensure_system_admin_friendships(account.id)

    remaining = await _cooldown_remaining(account.id)
    if remaining is not None and await has_completed_web_login(account.id):
        return AuthTokenReply(
            token=None,
            role=account.role,
            account_id=account.id,
            cooldown_remaining=remaining,
        )

    issued = await issue_web_auth_token(account.id, issued_via_telegram_user_id=user_id)
    return AuthTokenReply(
        token=issued.token,
        role=account.role,
        account_id=account.id,
    )


__all__ = ["AuthTokenReply", "issue_auth_token_reply"]
