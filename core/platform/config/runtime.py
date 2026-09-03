"""Runtime-слой поверх .env: ключ OpenRouter из app_settings (вкладка «Параметры»).

Исторический контекст (2026-08-05): `_runtime_openrouter_key` ниже — один ключ на ВЕСЬ
процесс, годный, пока в системе один пользователь (владелец). После появления self-serve
бота (несколько аккаунтов) это перестало быть безопасным допущением: LLM-вызов внутри
чужого запроса видел бы ключ владельца (или последнего, кто его сохранил через
PATCH /api/settings), а не ключ аккаунта, который реально сделал запрос.
`_current_account_id` (ContextVar) + `_account_key_cache` ниже —
per-request/per-апдейт контекст, который `api.security.require_account(_context)` (HTTP) и
`bot_app.run`'s account-middleware (Telegram) выставляют на время обработки. Этот модуль —
`platform`, ему нельзя знать про Postgres — сам SELECT в `account_settings` делает
`core.platform.repo.settings.prime_runtime_openrouter_key_for_account`, сюда попадает только готовое
значение (`cache_account_openrouter_key`), тем же приёмом, что уже `set_runtime_openrouter_key`
ниже получает готовый ключ из `core.platform.repo.settings.load_openrouter_key_into_runtime`.
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.platform.config.settings import CoreSettings

# Ключ OpenRouter, введённый на странице «Параметры» (хранится в app_settings в БД).
# Легаси-фолбэк: используется, когда per-request контекст аккаунта не выставлен (фоновые
# задачи/скрипты/бот вне обработки апдейта) — см. докстринг модуля.
_runtime_openrouter_key: str | None = None
# Исходный .env-ключ до первой подмены с фронта (для отката при очистке БД-ключа).
_env_openrouter_key: str | None = None

# --- Per-request контекст аккаунта (Этап 5 fix) ---

_current_account_id: ContextVar[int | None] = ContextVar("current_account_id", default=None)
# account_id -> (ключ или "", когда закэширован).
#
# ДВА разных срока, и путать их нельзя (прод-баг 2026-08-27..31, «Missing Authentication header»):
#  • _ACCOUNT_KEY_REFRESH_S — как часто `prime_runtime_openrouter_key_for_account` перечитывает
#    БД. Свежесть важнее одного лишнего SELECT раз в 15 с на активный аккаунт.
#  • _ACCOUNT_KEY_RETAIN_S — сколько запись вообще живёт в кэше и считается пригодной на ЧТЕНИИ.
#
# Раньше это была одна константа 15 с, и `current_account_openrouter_key()` отдавал "" всем,
# кто спросил позже 15-й секунды запроса/задачи. Любой LLM-вызов длиннее 15 с (а второй вызов
# сценария — ремонт сопроводительного — приходится на ~25-ю секунду) уходил в OpenRouter
# С ПУСТЫМ ключом и получал 401 по всей цепочке моделей: в журнале это выглядело как «провайдер
# лежит», хотя ключ был на месте. Держать ключ прочитанным дольше безопасно: запись ключа
# инвалидирует кэш явно (`core.platform.openrouter_keys._apply_key` →
# `cache_account_openrouter_key`), TTL для этого не нужен.
_account_key_cache: dict[int, tuple[str, float]] = {}
_ACCOUNT_KEY_REFRESH_S = 15.0
_ACCOUNT_KEY_RETAIN_S = 900.0
# Совместимость: имя читают тесты/старые импорты — это именно интервал обновления.
_ACCOUNT_KEY_CACHE_TTL_S = _ACCOUNT_KEY_REFRESH_S


def set_runtime_openrouter_key(key: str | None) -> None:
    """Обновить действующий ключ OpenRouter (БД / вкладка «Параметры»).

    Кладём и в in-process holder, и в кэшированные `CoreSettings.openrouter_api_key`.
    None/пусто — откат на исходный .env-ключ.
    """
    global _runtime_openrouter_key, _env_openrouter_key
    from core.platform.config.settings import get_settings

    normalized = (key or "").strip() or None
    _runtime_openrouter_key = normalized
    settings = get_settings()
    if _env_openrouter_key is None:
        _env_openrouter_key = settings.openrouter_api_key
    settings.openrouter_api_key = normalized or _env_openrouter_key


def runtime_openrouter_key() -> str:
    """Ключ OpenRouter из БД, либо '' если не задан (фолбэк на .env). Легаси/фоновый путь —
    предпочитай `current_account_openrouter_key()` там, где есть per-request контекст."""
    return _runtime_openrouter_key or ""


def set_current_account_id(account_id: int | None) -> Token[int | None]:
    """Выставить account_id текущего запроса/апдейта на время `try/finally` вызывающей
    стороны (`api.security.require_account(_context)`, `bot_app.run`'s account-middleware).
    Возвращает `Token` для `reset_current_account_id` — тот же паттерн, что
    `core.platform.llm.usage.begin_usage_capture`/`end_usage_capture`."""
    return _current_account_id.set(account_id)


def reset_current_account_id(token: Token[int | None]) -> None:
    _current_account_id.reset(token)


def current_account_id() -> int | None:
    """account_id текущего запроса/фоновой задачи (см. `set_current_account_id`), либо `None`
    вне такого контекста (CLI-скрипт, системная фоновая задача без личности)."""
    return _current_account_id.get()


def cache_account_openrouter_key(account_id: int, key: str | None) -> None:
    """Положить (или обновить) закэшированный ключ аккаунта — зовёт
    `core.platform.repo.settings.prime_runtime_openrouter_key_for_account` после
    реального SELECT."""
    _evict_stale_account_keys()
    _account_key_cache[account_id] = ((key or "").strip(), time.monotonic())


def account_openrouter_key_cache_stale(account_id: int) -> bool:
    """True — кэша нет или он старше интервала обновления, `prime_...` перечитает БД."""
    _evict_stale_account_keys()
    cached = _account_key_cache.get(account_id)
    return cached is None or (time.monotonic() - cached[1]) >= _ACCOUNT_KEY_REFRESH_S


def _evict_stale_account_keys() -> None:
    """Выкинуть давно не обновлявшиеся записи — без этого словарь копит ключи ушедших аккаунтов
    навсегда. Порог — срок ХРАНЕНИЯ (`_ACCOUNT_KEY_RETAIN_S`), не интервал обновления: выкидывать
    запись через 15 с значило бы отбирать ключ у уже идущего LLM-вызова. Вызывается на каждой
    операции: O(n) по числу аккаунтов, n — десятки, дёшево."""
    if not _account_key_cache:
        return
    now = time.monotonic()
    stale = [
        aid for aid, (_, ts) in _account_key_cache.items() if now - ts >= _ACCOUNT_KEY_RETAIN_S
    ]
    for aid in stale:
        _account_key_cache.pop(aid, None)


def current_account_openrouter_key() -> str:
    """Ключ OpenRouter аккаунта ТЕКУЩЕГО запроса/апдейта (per-request контекст, Этап 5 fix).

    '' — либо контекст не выставлен (фон/скрипт — фолбэк на `runtime_openrouter_key()`), либо
    у этого аккаунта своего ключа нет. Для запроса с `current_account_id()` `get_chat_model`
    берёт ТОЛЬКО этот ключ (пустой = нет ключа), без фолбэка на runtime/.env владельца.
    """
    account_id = _current_account_id.get()
    if account_id is None:
        return ""
    cached = _account_key_cache.get(account_id)
    if cached is None:
        return ""
    # Порог чтения — срок ХРАНЕНИЯ, не интервал обновления: за 15 с не успевает даже один
    # LLM-вызов, и старая проверка отбирала ключ у запроса прямо посреди работы (401 «Missing
    # Authentication header» в проде). Отзыв/смена ключа сюда доезжают не по таймеру, а явной
    # инвалидацией из `openrouter_keys._apply_key`.
    if time.monotonic() - cached[1] >= _ACCOUNT_KEY_RETAIN_S:
        return ""
    return cached[0]


def reset_runtime_for_tests() -> None:
    """Сбросить runtime-holder + per-account контекст/кэш (только тесты)."""
    global _runtime_openrouter_key, _env_openrouter_key
    _runtime_openrouter_key = None
    _env_openrouter_key = None
    _account_key_cache.clear()


def apply_runtime_to(settings: CoreSettings) -> CoreSettings:
    """Если runtime-ключ уже задан — наложить на свежий экземпляр settings."""
    if _runtime_openrouter_key:
        settings.openrouter_api_key = _runtime_openrouter_key
    return settings


__all__ = [
    "account_openrouter_key_cache_stale",
    "apply_runtime_to",
    "cache_account_openrouter_key",
    "current_account_id",
    "current_account_openrouter_key",
    "reset_current_account_id",
    "reset_runtime_for_tests",
    "runtime_openrouter_key",
    "set_current_account_id",
    "set_runtime_openrouter_key",
]
