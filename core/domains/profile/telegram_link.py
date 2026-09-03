"""Привязка Telegram-владельца через одноразовый токен.

«Владелец» — это больше не
запись `telegram_owner` в `app_settings`, а строка `accounts` с `role='owner'`
(`core.platform.repo.accounts`). Остаются в `app_settings` (глобальные, не аккаунт-скоуп):

- `telegram_link_token` — pending-токен привязки (TTL 10 мин): выпускается ДО существования
  аккаунта, привязывать его не к чему;
- `telegram_bot_identity` — кэш `getMe` (username бота): факт про сам бот, общий для всех.

Чистые функции (хэш, payload `/start`) + async-repo через
`core.platform.repo.settings`/`core.platform.repo.accounts`.
Модуль живёт в `profile`, не в `bot_app`: тем же кодом пользуется API.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict

from core.platform.db.pool import Executor
from core.platform.repo.accounts import (
    AccountRecord,
    Role,
    disable_account,
    get_owner_account,
    upsert_account,
)
from core.platform.repo.settings import get_setting, set_setting

logger = logging.getLogger(__name__)

# Значение ИЛИ async-резолвер без аргументов — `consume_token` зовёт резолвер только
# ПОСЛЕ успешной валидации токена, чтобы дорогой/с побочными эффектами резолвер (env-allowlist
# + DB-owner проверка) не платился на невалидном/протухшем токене.
RoleResolver = Role | Callable[[], Awaitable[Role]]

KEY_LINK_TOKEN = "telegram_link_token"
KEY_BOT_IDENTITY = "telegram_bot_identity"

# Deep-link `?start=` ≤ 64 символов, только [A-Za-z0-9_-] (Bot API).
LINK_PAYLOAD_PREFIX = "link_"
TOKEN_TTL = timedelta(minutes=10)
# 24 байта → ~32 символа urlsafe; `link_` + токен ≈ 37 ≤ 64.
_TOKEN_NBYTES = 24


class TelegramLinkTokenRecord(BaseModel):
    """Pending одноразового токена: в БД только sha256, сырой токен не храним."""

    model_config = ConfigDict(extra="ignore")

    token_sha256: str
    expires_at: datetime


class TelegramBotIdentity(BaseModel):
    """Кэш ответа getMe (username бота для deep-link / UI)."""

    model_config = ConfigDict(extra="ignore")

    username: str
    fetched_at: datetime


class IssuedLinkToken(BaseModel):
    """Свежевыпущенный токен: сырое значение уходит только в deep-link, не в PG."""

    token: str
    expires_at: datetime

    @property
    def start_payload(self) -> str:
        return f"{LINK_PAYLOAD_PREFIX}{self.token}"


def hash_token(raw_token: str) -> str:
    """sha256 сырого токена → hex (что пишем в `telegram_link_token`)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_raw_token() -> str:
    """Одноразовый токен: `secrets.token_urlsafe` → только [A-Za-z0-9_-]."""
    return secrets.token_urlsafe(_TOKEN_NBYTES)


def extract_link_token(start_payload: str) -> str | None:
    """Извлечь сырой токен из `/start` payload `link_<token>`; иначе None."""
    raw = (start_payload or "").strip()
    if not raw.startswith(LINK_PAYLOAD_PREFIX):
        return None
    token = raw[len(LINK_PAYLOAD_PREFIX) :]
    if not token or not _is_urlsafe_token(token):
        return None
    return token


def build_deep_link(bot_username: str, start_payload: str) -> str:
    """`https://t.me/<bot>?start=<payload>` — без @, для кнопки «Открыть Telegram»."""
    clean = bot_username.strip().lstrip("@")
    return f"https://t.me/{clean}?start={start_payload}"


def _is_urlsafe_token(token: str) -> bool:
    return all(c.isalnum() or c in "-_" for c in token)


def link_token_from_mapping(raw: Any) -> TelegramLinkTokenRecord | None:
    """Разобрать jsonb `telegram_link_token`; мусор / пусто → None."""
    if not isinstance(raw, dict):
        return None
    try:
        return TelegramLinkTokenRecord.model_validate(raw)
    except Exception:
        return None


def bot_identity_from_mapping(raw: Any) -> TelegramBotIdentity | None:
    """Разобрать jsonb `telegram_bot_identity`; мусор / пусто → None."""
    if not isinstance(raw, dict):
        return None
    try:
        return TelegramBotIdentity.model_validate(raw)
    except Exception:
        return None


def is_token_expired(record: TelegramLinkTokenRecord, *, now: datetime | None = None) -> bool:
    """True, если pending-токен протух (сравнение в UTC)."""
    now = now or datetime.now(UTC)
    expires = record.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return now >= expires


async def get_owner(*, db: Executor | None = None) -> AccountRecord | None:
    """Текущий привязанный владелец (`accounts.role='owner'`); нет строки → None."""
    return await get_owner_account(db=db)


async def set_owner(
    *,
    user_id: int,
    chat_id: int,
    username: str | None = None,
    role: Role = "owner",
    db: Executor | None = None,
) -> AccountRecord:
    """Завести / перелинковать `accounts` строку с указанной ролью (по умолчанию — owner,
    сохраняет прежнее поведение вызывающих, не решивших роль сами).

    Название — историческое; `role` НЕ решается здесь: политику «кто может стать
    owner» (env-allowlist) знает только `bot_app.access` (core-слой не должен на него
    ссылаться) — вызывающая сторона обязана резолвить роль сама и передать её (M7,
    plans/multitenancy_gaps_2026_08_06.md §3.11/§6). `upsert_account` не меняет `role` при
    реактивации существующего telegram_user_id — значение здесь важно только для первой
    привязки.
    """
    return await upsert_account(
        telegram_user_id=user_id,
        telegram_username=(username.lstrip("@") if username else None) or None,
        telegram_chat_id=chat_id,
        role=role,
        db=db,
    )


async def get_link_token(*, db: Executor | None = None) -> TelegramLinkTokenRecord | None:
    """Pending-токен (если есть и парсится); иначе None."""
    raw = await get_setting(KEY_LINK_TOKEN, default=None, account_id=None, db=db)
    return link_token_from_mapping(raw)


async def clear_link_token(*, db: Executor | None = None) -> None:
    """Сбросить pending-токен (после consume / истечения / отмены)."""
    await set_setting(KEY_LINK_TOKEN, None, account_id=None, db=db)


async def create_link_token(
    *,
    db: Executor | None = None,
    now: datetime | None = None,
) -> IssuedLinkToken:
    """Выпустить одноразовый токен: в PG — только sha256 + expires_at.

    Предыдущий pending-токен перезаписывается (новый deep-link из веба = единственный живой).
    """
    now = now or datetime.now(UTC)
    raw = generate_raw_token()
    expires_at = now + TOKEN_TTL
    record = TelegramLinkTokenRecord(token_sha256=hash_token(raw), expires_at=expires_at)
    await set_setting(KEY_LINK_TOKEN, record.model_dump(mode="json"), account_id=None, db=db)
    return IssuedLinkToken(token=raw, expires_at=expires_at)


async def consume_token(
    raw_token: str,
    *,
    user_id: int,
    chat_id: int,
    username: str | None = None,
    role: RoleResolver = "owner",
    db: Executor | None = None,
    now: datetime | None = None,
) -> AccountRecord | None:
    """Валидация одноразового токена → завести/перелинковать `accounts`-строку и сбросить pending.

    Невалидный / протухший / чужой токен → None. Протухший pending при этом чистим,
    чтобы не оставлять мёртвую строку до следующего create.

    `role` резолвит вызывающая сторона: владельцем становится только совпадение с
    env-allowlist (тот же принцип, что уже у `bot_app.services.auth_token`) — иначе member.
    Дефолт `"owner"` сохранён ради обратной совместимости вызывающих, которые ещё не
    прокидывают роль явно. Если `role` — async-callable, он резолвится ТОЛЬКО здесь, после
    всех проверок токена, — невалидный/протухший токен не платит за (возможно небесплатный)
    резолвер.
    """
    now = now or datetime.now(UTC)
    token = (raw_token or "").strip()
    if not token or not _is_urlsafe_token(token):
        return None

    record = await get_link_token(db=db)
    if record is None:
        return None

    if is_token_expired(record, now=now):
        await clear_link_token(db=db)
        return None

    if not secrets.compare_digest(record.token_sha256, hash_token(token)):
        return None

    # Одноразовость: сжечь pending до записи owner, чтобы гонка двух /start не
    # привязала двух юзеров к одному токену.
    await clear_link_token(db=db)

    resolved_role = await role() if callable(role) else role
    account = await set_owner(
        user_id=user_id, chat_id=chat_id, username=username, role=resolved_role, db=db
    )
    logger.info(
        "telegram_link: привязан user_id=%s chat_id=%s username=%s role=%s",
        account.telegram_user_id,
        account.telegram_chat_id,
        account.telegram_username,
        account.role,
    )
    return account


async def unlink(*, account_id: int, db: Executor | None = None) -> None:
    """Отвязать СВОЙ аккаунт (статус → disabled), не глобального владельца.

    M7 (plans/multitenancy_gaps_2026_08_06.md §3.11): раньше эта функция безусловно гасила
    `role='owner'` — любой залогиненный member мог одним запросом выключить владельца.
    `account_id` резолвит вызывающая сторона по личности запроса, не по `get_owner_account()`.
    Pending link-токен (глобальный, не аккаунт-скоуп) сбрасывается всегда — он не принадлежит
    ни одному конкретному аккаунту, оставлять мёртвый pending нет смысла.
    """
    await disable_account(account_id, db=db)
    await clear_link_token(db=db)


async def get_bot_identity(*, db: Executor | None = None) -> TelegramBotIdentity | None:
    """Кэш getMe; нет / мусор → None."""
    raw = await get_setting(KEY_BOT_IDENTITY, default=None, account_id=None, db=db)
    return bot_identity_from_mapping(raw)


async def set_bot_identity(
    username: str,
    *,
    db: Executor | None = None,
    now: datetime | None = None,
) -> TelegramBotIdentity:
    """Обновить кэш username бота (без @)."""
    now = now or datetime.now(UTC)
    clean = username.strip().lstrip("@")
    identity = TelegramBotIdentity(username=clean, fetched_at=now)
    await set_setting(KEY_BOT_IDENTITY, identity.model_dump(mode="json"), account_id=None, db=db)
    return identity


async def clear_bot_identity(*, db: Executor | None = None) -> None:
    """Сбросить кэш getMe."""
    await set_setting(KEY_BOT_IDENTITY, None, account_id=None, db=db)


__all__ = [
    "KEY_BOT_IDENTITY",
    "KEY_LINK_TOKEN",
    "LINK_PAYLOAD_PREFIX",
    "TOKEN_TTL",
    "IssuedLinkToken",
    "RoleResolver",
    "TelegramBotIdentity",
    "TelegramLinkTokenRecord",
    "bot_identity_from_mapping",
    "build_deep_link",
    "clear_bot_identity",
    "clear_link_token",
    "consume_token",
    "create_link_token",
    "extract_link_token",
    "generate_raw_token",
    "get_bot_identity",
    "get_link_token",
    "get_owner",
    "hash_token",
    "is_token_expired",
    "link_token_from_mapping",
    "set_bot_identity",
    "set_owner",
    "unlink",
]
