"""Доступ в боте: «аккаунт» vs «оператор».

- **Аккаунт** — любой, кто прошёл self-serve `/start` (`bot_app.services.auth_token`) —
  owner ИЛИ member. Гейт — `bot_app.filters.IsAccount` / `resolve_account()` здесь.
- **Оператор** — DB-owner (`accounts.role='owner'`) ∪ env-allowlist. Единственный,
  кому доступны операторские действия (одобрение заявок на OpenRouter-ключ и т.п.) — гейт
  `bot_app.filters.IsAdmin` / `is_allowed_admin()` ниже, как и раньше.

Env (`ADMIN_USER_ID` / `ADMIN_USER_IDS` / `ADMIN_USERNAMES`) — бутстрап и мультиаккаунт.
Привязка из веба заводит/обновляет строку `accounts`; `resolve_owner()` читает её с кэшем 60 с.

Пустой конфиг больше НЕ означает «отвечаем всем» (дыра при публичном боте).
Если не настроено ничего — `/start` заводит self-serve member-аккаунт, как и для любого
другого незнакомца (`cmd_start_guest` в menu, `bot_app.services.auth_token`); владельцем
может стать только совпадение с env-allowlist, «первый нажавший» больше не бутстрапится.
Остальное молча отсекает IsAdmin.
"""

from __future__ import annotations

import time
from typing import Any

from bot_app.config import BotSettings, get_bot_settings
from core.domains.profile.telegram_link import get_owner
from core.platform.repo.accounts import (
    AccountRecord,
    get_account_by_telegram_user_id,
    upsert_account,
)

OWNER_CACHE_TTL_S = 60.0
# resolve_account зовётся на КАЖДЫЙ апдейт (account-context middleware в bot_app.run, Этап 5
# fix для LLM key routing) — короче, чем у владельца: свежесть self-serve чуть важнее (только
# что созданный member-аккаунт должен стать виден без минуты ожидания).
ACCOUNT_CACHE_TTL_S = 15.0

_MISSING: Any = object()
_cached_owner: Any = _MISSING
_cached_at_mono: float = 0.0
_account_cache: dict[int, tuple[AccountRecord | None, float]] = {}


def invalidate() -> None:
    """Сбросить кэш resolve_owner/resolve_account после линковки/отвязки/новой self-serve
    привязки."""
    global _cached_owner, _cached_at_mono
    _cached_owner = _MISSING
    _cached_at_mono = 0.0
    _account_cache.clear()


async def resolve_owner(*, force: bool = False) -> AccountRecord | None:
    """Владелец из `accounts` (role='owner'); in-process кэш TTL 60 с."""
    global _cached_owner, _cached_at_mono
    now = time.monotonic()
    if not force and _cached_owner is not _MISSING and (now - _cached_at_mono) < OWNER_CACHE_TTL_S:
        return _cached_owner
    owner = await get_owner()
    _cached_owner = owner
    _cached_at_mono = now
    return owner


def _parse_ids(settings: BotSettings) -> frozenset[int]:
    ids: set[int] = set()
    if settings.admin_user_id:
        ids.add(int(settings.admin_user_id))
    raw = (settings.admin_user_ids or "").strip()
    if raw:
        for part in raw.replace(";", ",").split(","):
            part = part.strip()
            if part.isdigit():
                ids.add(int(part))
    return frozenset(ids)


def _parse_usernames(settings: BotSettings) -> frozenset[str]:
    names: set[str] = set()
    raw = (settings.admin_usernames or "").strip()
    if raw:
        for part in raw.replace(";", ",").split(","):
            name = part.strip().lstrip("@").lower()
            if name:
                names.add(name)
    return frozenset(names)


def env_allowlist_configured(settings: BotSettings | None = None) -> bool:
    """В .env задан хотя бы один id или @username владельца."""
    settings = settings or get_bot_settings()
    return bool(_parse_ids(settings) or _parse_usernames(settings))


def matches_env_allowlist(
    *,
    user_id: int | None,
    username: str | None,
    settings: BotSettings | None = None,
) -> bool:
    """Совпадение с ADMIN_* из .env (без DB)."""
    settings = settings or get_bot_settings()
    if user_id is not None and user_id in _parse_ids(settings):
        return True
    return bool(username and username.lstrip("@").lower() in _parse_usernames(settings))


def matches_db_owner(
    owner: AccountRecord | None,
    *,
    user_id: int | None,
    username: str | None,
) -> bool:
    """Совпадение с привязанным владельцем (`accounts.role='owner'`)."""
    if owner is None:
        return False
    if user_id is not None and user_id == owner.telegram_user_id:
        return True
    if username and owner.telegram_username:
        return username.lstrip("@").lower() == owner.telegram_username.lstrip("@").lower()
    return False


async def is_access_configured(settings: BotSettings | None = None) -> bool:
    """True, если есть env-allowlist или привязка в PG."""
    if env_allowlist_configured(settings):
        return True
    return await resolve_owner() is not None


def is_open_bot_mode(settings: BotSettings | None = None) -> bool:
    """Env-allowlist пуст (нет бутстрапа в .env).

    Раньше пустой конфиг = «отвечаем всем». TB-1.4: это только сигнал «нет ADMIN_*»;
    доступ даёт DB-owner ∪ env, иначе — только /start с подсказкой привязки.
    """
    return not env_allowlist_configured(settings)


async def is_allowed_admin(
    *,
    user_id: int | None,
    username: str | None,
    settings: BotSettings | None = None,
) -> bool:
    """True, если пользователь — владелец: DB-owner ∪ env-allowlist."""
    if user_id is None and not username:
        return False
    settings = settings or get_bot_settings()
    if matches_env_allowlist(user_id=user_id, username=username, settings=settings):
        return True
    owner = await resolve_owner()
    return matches_db_owner(owner, user_id=user_id, username=username)


async def resolve_owner_account_id() -> int | None:
    """account_id владельца для доменных вызовов, которые пока обслуживают только его
    (`IsAdmin` — гейт хендлера) — карточки/дайджест/discovery и т.п. не ретрофичены на
    произвольный account_id самого пишущего в Этапе 5 (план §9, узкий список расширенных
    функций — см. `resolve_account`). None — владелец ещё не привязан (бутстрап)."""
    owner = await resolve_owner()
    return owner.id if owner is not None else None


async def resolve_account(*, user_id: int | None) -> AccountRecord | None:
    """Любой АКТИВНЫЙ аккаунт (owner ИЛИ member) по Telegram user_id (Этап 5, план §5:
    «аккаунт — есть у любого, кто прошёл /start»). In-process кэш TTL 15 с (`ACCOUNT_CACHE_
    TTL_S`) — зовётся на каждый апдейт из account-context middleware (`bot_app.run`, LLM key
    routing fix) и из `IsAccount`. `status='disabled'` (отвязанный
    владелец) не считается.
    """
    if user_id is None:
        return None
    now = time.monotonic()
    cached = _account_cache.get(user_id)
    if cached is not None and (now - cached[1]) < ACCOUNT_CACHE_TTL_S:
        return cached[0]
    account = await get_account_by_telegram_user_id(user_id)
    result = account if (account is not None and account.status == "active") else None
    _account_cache[user_id] = (result, now)
    return result


async def resolve_operator_account(
    *, user_id: int, username: str | None, chat_id: int | None = None
) -> AccountRecord:
    """Строка `accounts` ОПЕРАТОРА (DB-owner ∪ env-allowlist), привязывая её на лету при
    первом обращении — тот же приём, что раньше жил прямо в `issue_auth_token_reply` (TB-6.3:
    чистый env-allowlist без DB-owner всё равно должен привязаться, иначе «В Telegram» пуши
    остаются заблокированы навсегда). Вызывающая сторона обязана сама проверить
    `is_allowed_admin(...)` до вызова — здесь личность уже считается операторской.
    """
    current = await resolve_owner()
    if current is not None and current.telegram_user_id == user_id:
        return current
    # upsert_account (не set_owner): chat_id тут может быть None (нет апдейта с чатом под
    # рукой в вызывающем коде) — upsert_account.coalesce сохранит уже записанный chat_id,
    # set_owner потребовал бы int и затёр бы его нулём.
    account = await upsert_account(
        telegram_user_id=user_id,
        telegram_username=(username.lstrip("@") if username else None) or None,
        telegram_chat_id=chat_id,
        role="owner",
    )
    invalidate()
    return account
