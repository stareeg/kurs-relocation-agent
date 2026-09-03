"""Аутентификация API: токен из Telegram-бота → личность аккаунта (Этап 2).

Три способа пройти периметр:
- расширение/боты — заголовок `X-API-Key`: статический ключ из .env (резолвится в аккаунт
  `role='owner'` — операторский служебный путь) ИЛИ действующий web-токен конкретного
  аккаунта (та же учётка работает и в вебе, и в
  расширении);
- фронт — httponly-cookie `copilot_auth` с сырым web-токеном (ставится `POST /auth/token`);
- программные клиенты — заголовок `X-Auth-Token` с тем же web-токеном.

Web-токен выпускает бот (кнопка «Токен авторизации»), в PG — только sha256, на колонках
конкретной строки `accounts` (`core.domains.profile.web_auth`), не в общем key/value.

`require_account` отдаёт `AccountContext | None`, а не голый bool/None, как раньше
(`require_auth`) — личность запроса теперь известна роутеру, а не восстанавливается заново
из глобального состояния (см. §0 плана). `None` — не «анонимный доступ», а «аккаунтов ещё нет
вообще» (bootstrap: свежая установка/CI до первой привязки Telegram) — периметр в этом окне
открыт для ВСЕХ запросов, как и до Этапа 2, а роутерам, которым для работы нужен account_id
(settings, avatar, …), есть куда упасть: `account_id=None` в `core.platform.repo.settings`
читает/пишет `app_settings`, тот же bootstrap-путь, что был единственным раньше. Как только
хоть один токен хоть кому-то выпущен — периметр закрыт навсегда, незалогиненный запрос
получает 401.

Запись токенов читается из PG с in-process кэшем (TTL 15 с): недоступный PG не роняет
запросы (аккаунтов «не видно» → периметр открыт, как на свежей установке).
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import Cookie, Depends, Header, HTTPException, Request

from api.config import get_settings
from core.domains.profile import web_auth
from core.platform.repo.accounts import AccountRecord, get_owner_account, touch_last_seen
from core.platform.repo.settings import (
    is_extension_confirmed,
    set_extension_confirmed,
    set_extension_version,
)

logger = logging.getLogger(__name__)

AUTH_COOKIE = "copilot_auth"
# Cookie живёт год: токен не надо «продлевать», выход — только явный логаут или перевыпуск в боте.
AUTH_COOKIE_MAX_AGE_S = 365 * 24 * 3600

_CACHE_TTL_S = 15.0


@dataclass(frozen=True, slots=True)
class AccountContext:
    """Личность запроса, разрешённая по токену (Этап 2)."""

    account_id: int
    telegram_user_id: int
    telegram_username: str | None
    role: Literal["owner", "member"]

    @classmethod
    def from_account(cls, account: AccountRecord) -> AccountContext:
        return cls(
            account_id=account.id,
            telegram_user_id=account.telegram_user_id,
            telegram_username=account.telegram_username,
            role=account.role,
        )


_cache_any_issued: bool | None = None
_cache_active_sessions: list[tuple[web_auth.SessionRecord, AccountRecord]] | None = None
_cache_loaded_at: float | None = None

# Аккаунты, для которых уже подтверждено (в этом процессе) «расширение работает» — не долбим
# is_extension_confirmed на каждый запрос из расширения после первого успеха.
_extension_confirmed_seen: set[int] = set()

# last_seen — throttle на 5 минут на аккаунт: не бьём Postgres UPDATE-ом на каждый запрос ради
# поля, которое и так меняется плавно (см. touch_account_last_seen).
_LAST_SEEN_TOUCH_S = 300.0
_last_seen_touched_at: dict[int, float] = {}


def client_ip(request: Request) -> str | None:
    """IP клиента с поправкой на цепочку Caddy → nginx(frontend) → api (deploy/Caddyfile,
    frontend/nginx.conf): только Caddy смотрит в интернет и сама выставляет X-Forwarded-For (не
    доверяя чужому значению на входе), поэтому первый адрес в списке — реальный клиент, не наш
    собственный прокси-хоп. Локально (без Caddy) заголовка нет — берём peer-адрес как есть."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


async def touch_account_last_seen(account_id: int, ip: str | None) -> None:
    """Отметить активность аккаунта — не чаще раза в 5 минут (throttle), вызывается на каждый
    аутентифицированный HTTP-запрос (`account_llm_context_middleware`). Заготовка под будущий
    admin-обзор «кто реально пользуется» и capacity planning под многопользовательский рост
    (не бизнес-логика прохождения периметра)."""
    now = time.monotonic()
    last = _last_seen_touched_at.get(account_id)
    if last is not None and (now - last) < _LAST_SEEN_TOUCH_S:
        return
    _last_seen_touched_at[account_id] = now
    await touch_last_seen(account_id, ip=ip)


def invalidate_web_auth_cache() -> None:
    """Сбросить кэш (после логина/логаута/перевыпуска токена).

    Заодно чистит `_extension_confirmed_seen`: id аккаунтов не переиспользуются в проде (serial
    PK), так что там это просто «на всякий случай» после логаута/перевыпуска, но в тестах
    (`tests/fake_accounts.py`, id всегда с 1) без этого отметка одного теста молча гасила бы
    проверку в следующем — эта функция и так вызывается в фикстурах до/после каждого теста.
    """
    global _cache_any_issued, _cache_active_sessions, _cache_loaded_at
    _cache_any_issued = None
    _cache_active_sessions = None
    _cache_loaded_at = None
    _extension_confirmed_seen.clear()
    _last_seen_touched_at.clear()


async def _note_extension_seen(account_id: int, *, extension_version: str | None = None) -> None:
    """Запрос прошёл периметр по X-Auth-Token/X-API-Key, а не по cookie — значит, это не
    веб-фронт (тот всегда шлёт cookie), а расширение или другой программный клиент. Само
    успешное обращение уже доказывает «расширение работает» — раньше это же поле выставлялось
    только руками, кнопкой «Расширение установлено» на фронте, которая ничего не проверяла и
    могла быть нажата даже когда расширение реально не достучалось до бэка (docs/problems.md,
    2026-08-05). Не даём странице «Расширение» просить подтвердить руками то, что уже видно по
    трафику. Лучшая попытка: недоступный PG просто откладывает отметку до следующего запроса.

    `extension_version` (из заголовка X-Extension-Version) — версия расширения аккаунта.
    Сохраняем best-effort для блока версионности на странице «Расширение» (новее → подсказка
    «вышла новая версия»). Пустую/нечестную не сохраняем (см. set_extension_version).
    """
    if account_id in _extension_confirmed_seen and not extension_version:
        return
    try:
        if not await is_extension_confirmed(account_id=account_id):
            await set_extension_confirmed(True, account_id=account_id)
        if extension_version:
            await set_extension_version(extension_version, account_id=account_id)
        _extension_confirmed_seen.add(account_id)
    except Exception as exc:  # noqa: BLE001 — фоновая отметка не должна ронять авторизацию
        logger.debug("api.security: авто-отметка extension_seen не удалась: %s", exc)


async def _load_cached(
    *, force: bool = False
) -> tuple[bool, list[tuple[web_auth.SessionRecord, AccountRecord]]]:
    """(бутстрап хоть раз закрывался?, активные сессии + их аккаунты) — TTL 15 с (hot path).

    Недоступный PG — не 500 на каждый запрос: аккаунты «не видны» → как на свежей
    установке (bootstrap открыт), тот же принцип, что был у
    `core.platform.repo.settings.get_setting` до Этапа 2 (единственная запись
    `web_auth_token` тоже тихо давала `default=None`).
    """
    global _cache_any_issued, _cache_active_sessions, _cache_loaded_at
    now = time.monotonic()
    if (
        not force
        and _cache_loaded_at is not None
        and (now - _cache_loaded_at) < _CACHE_TTL_S
        and _cache_any_issued is not None
        and _cache_active_sessions is not None
    ):
        return _cache_any_issued, _cache_active_sessions
    try:
        any_issued = await web_auth.any_web_auth_token_issued()
        active_sessions = await web_auth.list_active_sessions_with_accounts()
    except Exception as exc:
        logger.debug("api.security: accounts недоступны (%s) — периметр как bootstrap", exc)
        any_issued, active_sessions = False, []
    _cache_any_issued = any_issued
    _cache_active_sessions = active_sessions
    _cache_loaded_at = now
    return any_issued, active_sessions


def _match_token(
    active_sessions: list[tuple[web_auth.SessionRecord, AccountRecord]], raw_token: str | None
) -> AccountRecord | None:
    token = (raw_token or "").strip()
    if not token:
        return None
    needle = web_auth.hash_token(token)
    for session, account in active_sessions:
        if secrets.compare_digest(session.token_sha256, needle):
            return account
    return None


async def _authenticate(
    x_api_key: str | None,
    x_auth_token: str | None,
    cookie_token: str | None,
    *,
    x_extension_version: str | None = None,
) -> tuple[AccountContext | None, bool]:
    """(личность запроса — если разрешена, бутстрап всё ещё открыт?).

    `x_extension_version` (заголовок X-Extension-Version) учитывается только для запросов из
    расширения (X-Auth-Token/X-API-Key), не для cookie-фронта — веб не шлёт этот заголовок.
    """
    settings = get_settings()
    any_issued, active_sessions = await _load_cached()

    if settings.api_key and x_api_key and hmac.compare_digest(x_api_key, settings.api_key):
        try:
            owner = await get_owner_account()
        except Exception as exc:
            logger.debug("api.security: get_owner_account недоступен (%s)", exc)
            owner = None
        if owner is not None:
            await _note_extension_seen(owner.id, extension_version=x_extension_version)
            return AccountContext.from_account(owner), not any_issued

    cookie_account = _match_token(active_sessions, cookie_token)
    if cookie_account is not None:
        return AccountContext.from_account(cookie_account), not any_issued

    for raw in (x_auth_token, x_api_key):
        account = _match_token(active_sessions, raw)
        if account is not None:
            await _note_extension_seen(account.id, extension_version=x_extension_version)
            return AccountContext.from_account(account), not any_issued

    return None, not any_issued


async def check_request_authed(
    x_api_key: str | None,
    x_auth_token: str | None,
    cookie_token: str | None,
    *,
    x_extension_version: str | None = None,
) -> bool:
    """Периметр пройден? Обёртка над `resolve_request_account` для мест, которым не нужна
    сама личность (историческое имя — совместимость с `/auth/status`, тестами)."""
    _account, authed = await resolve_request_account(
        x_api_key, x_auth_token, cookie_token, x_extension_version=x_extension_version
    )
    return authed


async def resolve_request_account(
    x_api_key: str | None,
    x_auth_token: str | None,
    cookie_token: str | None,
    *,
    x_extension_version: str | None = None,
) -> tuple[AccountContext | None, bool]:
    """(личность запроса — если конкретный аккаунт разрешён по токену, периметр пройден?).

    `account=None, authed=True` — легальная комбинация: периметр открыт (bootstrap, ИЛИ
    статический X-API-Key без привязанного владельца), но резолвить именно «чей» это
    запрос нечем. Вызывающая сторона (`/auth/status`) в этом случае показывает состояние
    владельца инсталляции, как и раньше единственная глобальная запись показывала себя
    всем — см. `api.routers.meta.auth.build_auth_status`.
    """
    account, bootstrap_open = await _authenticate(
        x_api_key, x_auth_token, cookie_token, x_extension_version=x_extension_version
    )
    return account, account is not None or bootstrap_open


async def require_account(
    x_api_key: str | None = Header(default=None),
    x_auth_token: str | None = Header(default=None),
    x_extension_version: str | None = Header(default=None, alias="X-Extension-Version"),
    copilot_auth: str | None = Cookie(default=None),
) -> AccountContext | None:
    """Зависимость FastAPI: личность запроса, либо `None` в окне bootstrap (см. модуль)."""
    account, bootstrap_open = await _authenticate(
        x_api_key, x_auth_token, copilot_auth, x_extension_version=x_extension_version
    )
    if account is not None:
        return account
    if bootstrap_open:
        return None
    raise HTTPException(status_code=401, detail="Не авторизован")


async def require_account_context(
    x_api_key: str | None = Header(default=None),
    x_auth_token: str | None = Header(default=None),
    x_extension_version: str | None = Header(default=None, alias="X-Extension-Version"),
    copilot_auth: str | None = Cookie(default=None),
) -> AccountContext:
    """Как `require_account`, но без bootstrap-`None` (Этап 3, план §1/§3).

    Для роутеров доменов, ретрофиченных под `account_id NOT NULL` (funnel/HR-переписка,
    дальше — preparation/offers/…): там `account_id=None` некуда упасть, в отличие от
    `app_settings`/аватара (`core.platform.repo.settings`, ещё key/value до первого
    аккаунта). Bootstrap здесь — не «работай анонимно», а «сначала привяжите Telegram» →
    401 с понятной причиной, а не `NotNullViolation`/`TypeError` где-то в глубине repo-слоя.
    """
    account, _bootstrap_open = await _authenticate(
        x_api_key, x_auth_token, copilot_auth, x_extension_version=x_extension_version
    )
    if account is not None:
        return account
    raise HTTPException(
        status_code=401,
        detail="Нужен аккаунт — привяжите Telegram (кнопка «Токен авторизации» в боте)",
    )


async def require_platform_admin(
    account: AccountContext = Depends(require_account_context),
) -> AccountContext:
    """Оператор установки: только `accounts.role='owner'`. Member и bootstrap — 403.

    Не хардкодим Telegram-username: владельца заводит бот по ADMIN_USERNAMES / ADMIN_USER_ID.
    UI-флаг `is_admin` на `/auth/status` — подсказка меню, этот гейт — источник правды.
    """
    if account.role != "owner":
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return account


__all__ = [
    "AUTH_COOKIE",
    "AUTH_COOKIE_MAX_AGE_S",
    "AccountContext",
    "check_request_authed",
    "client_ip",
    "invalidate_web_auth_cache",
    "require_account",
    "require_account_context",
    "require_platform_admin",
    "resolve_request_account",
    "touch_account_last_seen",
]
