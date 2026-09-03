"""Repository «Параметры» (FR-11/12, Этап 2: account_settings).

`get_setting`/`set_setting` принимают обязательный (может быть `None`) `account_id`:

- `account_id` задан → строка в `account_settings` (PK `(account_id, key)`, RLS с Этапа 1,
  читается/пишется через `account_scope()` — колонка + RLS, как весь остальной план требует
  «RLS поверх ручной фильтрации, не вместо неё»);
- `account_id=None` → `app_settings` — таблица не исчезла, а сузилась до системных ключей
  (`telegram_link_token`, `telegram_bot_identity` — они physически не привязаны ни к какому
  аккаунту) и до временного bootstrap-хранилища «Параметров» в окне между свежей установкой
  и первой привязкой Telegram (пока `accounts` пуста, писать пользовательские настройки больше
  некуда — `require_account` в этом окне возвращает `None`, см. api/security.py).

При отсутствии строки в БД возвращаем Python-дефолты (совпадают с сидом миграции 0050 и `.env`),
чтобы API не ломался на пустой таблице. Полный набор дефолтов (с доменными значениями —
`candidate_profile`, `telegram_prefs`, …) собирает `core.app.settings_defaults.
default_app_settings_values` — этот модуль их не знает, только читает/пишет готовые jsonb.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

DEFAULT_SCORING_WEIGHTS: dict[str, int] = {
    "salary": 20,
    "work_format": 20,
    "grade_match": 15,
    "role_content": 15,
    "management": 15,
    "company": 15,
}

# Важность 1-5 для UI шкалы в «Резюме»; проценты считаются из этих уровней.
# Храним отдельно: round-trip через проценты ломает отображение после перезагрузки.
DEFAULT_SCORING_IMPORTANCE: dict[str, int] = {
    "salary": 4,
    "work_format": 4,
    "grade_match": 3,
    "role_content": 3,
    "management": 3,
    "company": 3,
}

# Пусто по умолчанию: предпочтения кандидата — из резюме (target/avoid, ред-флаги, формат).
# Power-user может задать ручные правила через API `company_adjustments`; в UI резюме их нет.
DEFAULT_COMPANY_ADJUSTMENTS: list[dict[str, Any]] = []


async def get_setting(
    key: str, default: Any = None, *, account_id: int | None, db: Executor | None = None
) -> Any:
    """Прочитать jsonb-значение по ключу; нет строки / ошибка PG → `default`.

    `account_id=None` → `app_settings` (системные ключи / bootstrap-окно до первого аккаунта);
    иначе — `account_settings` этого аккаунта, через `account_scope()` (RLS), если вызывающая
    сторона не передала уже открытое `db` (транзакция/тест).
    Обёрнуто в try: не поднятый пул (PG лежит, тесты без БД) — тоже «нет данных», а не
    RuntimeError наружу (иначе /auth/status и периметр падали бы 500 при недоступной БД).
    """
    try:
        if account_id is None:
            executor = db or get_pool()
            row = await executor.fetchrow("select value from app_settings where key = $1", key)
        elif db is not None:
            row = await db.fetchrow(
                "select value from account_settings where account_id = $1 and key = $2",
                account_id,
                key,
            )
        else:
            async with account_scope(account_id) as scoped:
                row = await scoped.fetchrow(
                    "select value from account_settings where account_id = $1 and key = $2",
                    account_id,
                    key,
                )
    except Exception as exc:
        logger.debug("settings: чтение %s (account_id=%s) недоступно: %s", key, account_id, exc)
        return default
    if row is None:
        return default
    return row_to_dict(row)["value"]


async def set_setting(
    key: str, value: Any, *, account_id: int | None, db: Executor | None = None
) -> None:
    """Upsert jsonb-значения; `updated_at` обновляется всегда.

    `value=None` → удалить строку: колонка `value` NOT NULL, а Python None asyncpg кодирует
    в SQL NULL (инцидент 2026-07-31: `clear_owner`/сброс `salary_min_override` падали с
    NotNullViolation). Семантика для читателя та же — `get_setting` вернёт default.
    """
    if account_id is None:
        executor = db or get_pool()
        if value is None:
            await executor.execute("delete from app_settings where key = $1", key)
            return
        await executor.execute(
            "insert into app_settings (key, value) values ($1, $2) "
            "on conflict (key) do update set value = excluded.value, updated_at = now()",
            key,
            value,
        )
        return

    async def _write(executor: Executor) -> None:
        if value is None:
            await executor.execute(
                "delete from account_settings where account_id = $1 and key = $2",
                account_id,
                key,
            )
            return
        await executor.execute(
            "insert into account_settings (account_id, key, value) values ($1, $2, $3) "
            "on conflict (account_id, key) do update set "
            "value = excluded.value, updated_at = now()",
            account_id,
            key,
            value,
        )

    if db is not None:
        await _write(db)
    else:
        async with account_scope(account_id) as scoped:
            await _write(scoped)


# AUTH-1: онбординг — jsonb-словарь флагов (`extension_confirmed`, …), не блокирует работу.
KEY_ONBOARDING = "onboarding"


async def is_extension_confirmed(*, account_id: int | None, db: Executor | None = None) -> bool:
    """Пользователь отметил «Расширение установлено» на шаге онбординга."""
    raw = await get_setting(KEY_ONBOARDING, default=None, account_id=account_id, db=db)
    return bool(isinstance(raw, dict) and raw.get("extension_confirmed"))


async def set_extension_confirmed(
    value: bool, *, account_id: int | None, db: Executor | None = None
) -> None:
    """Проставить/снять флаг «Расширение установлено» (merge, не перетирая соседние флаги)."""
    raw = await get_setting(KEY_ONBOARDING, default=None, account_id=account_id, db=db)
    state = dict(raw) if isinstance(raw, dict) else {}
    state["extension_confirmed"] = bool(value)
    await set_setting(KEY_ONBOARDING, state, account_id=account_id, db=db)


async def get_extension_version(
    *, account_id: int | None, db: Executor | None = None
) -> str | None:
    """Версия расширения, которой пользуется аккаунт (захвачена из X-Extension-Version).

    Хранится отдельным ключом `extension_version` в account_settings, не внутри `onboarding`,
    чтобы менять без merge. `None` — расширение ни разу не обращалось / версию не присылало.
    """
    raw = await get_setting("extension_version", default=None, account_id=account_id, db=db)
    return raw if isinstance(raw, str) and raw.strip() else None


async def set_extension_version(
    version: str, *, account_id: int | None, db: Executor | None = None
) -> None:
    """Запомнить версию расширения аккаунта (X-Extension-Version при запросе расширения).

    Best-effort: недоступный PG тихо пропускается — это декоративная метка, не критичный путь.
    Пустую/нечестную версию не сохраняем.
    """
    cleaned = version.strip() if isinstance(version, str) else ""
    if not cleaned:
        return
    await set_setting("extension_version", cleaned, account_id=account_id, db=db)


# --- Heartbeat раннеров расширения (автоотклики / автопросмотр) ---
# Раннер живёт в service worker'е MV3 — его молчание («SW усыплён» / «ручка отвалилась» /
# «очередь пуста») в проде неотличимо без явного тик-репорта (инцидент 2026-08-27..28).
# Храним `{at, summary, logged_at}` в отдельном jsonb-ключе; рутинный heartbeat в журнал
# троттлится (`should_log_runner_tick`), проблемный/активный тик логируется всегда сценарием.
_RUNNER_HEARTBEAT_INTERVAL_S = 1800.0


async def record_runner_tick(
    key: str,
    *,
    account_id: int | None,
    summary: dict[str, Any] | None = None,
    logged: bool = False,
    db: Executor | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    raw = await get_setting(key, default=None, account_id=account_id, db=db)
    prev = raw if isinstance(raw, dict) else {}
    await set_setting(
        key,
        {
            "at": now,
            "summary": summary or {},
            "logged_at": now if logged else prev.get("logged_at"),
        },
        account_id=account_id,
        db=db,
    )


async def get_runner_tick(
    key: str, *, account_id: int | None, db: Executor | None = None
) -> dict[str, Any] | None:
    raw = await get_setting(key, default=None, account_id=account_id, db=db)
    return raw if isinstance(raw, dict) else None


async def should_log_runner_tick(
    key: str, *, account_id: int | None, db: Executor | None = None
) -> bool:
    """Пора ли писать рутинный heartbeat (не чаще раза в 30 мин); проблемные тики минуют это."""
    entry = await get_runner_tick(key, account_id=account_id, db=db)
    stamp = (entry or {}).get("logged_at")
    if not isinstance(stamp, str):
        return True
    try:
        last = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    return (datetime.now(UTC) - last).total_seconds() >= _RUNNER_HEARTBEAT_INTERVAL_S


async def is_openrouter_key_configured(
    *, account_id: int | None, db: Executor | None = None
) -> bool:
    """Ключ задан именно у ЭТОГО аккаунта (БД) — без фолбэка на `.env`.

    До фикса (docs/problems.md, 2026-08-05) фолбэк на `.env` делал бейдж/кнопку «Сбросить» на
    «Параметры» бессмысленными для владельца: `.env` хранит ключ оператора, флаг всегда читался
    как True независимо от того, что реально лежит в БД у аккаунта — сброс происходил (строка
    удалялась), но UI никогда не показывал «не задан» и не пускал вставить новый. Тот же фолбэк
    ложно показывал «настроен» и другу без собственного ключа (self-serve флоу, Этап 5 плана) —
    вводил в заблуждение про BYOK-статус аккаунта. «Какой ключ реально использовать на вызове» —
    отдельный вопрос, решается через `load_openrouter_key_into_runtime`/
    `prime_runtime_openrouter_key_for_account` (runtime-holder в `core.config`), фолбэк на `.env`
    там сохранён осознанно.
    """
    stored = await get_setting("openrouter_api_key", default=None, account_id=account_id, db=db)
    return isinstance(stored, str) and bool(stored.strip())


async def get_openrouter_key_set_at(
    *, account_id: int | None, db: Executor | None = None
) -> datetime | None:
    """Когда ключ OpenRouter был сохранён/обновлён в последний раз (`updated_at` строки).

    Для подписи «Дата вставки токена» в блоке OpenRouter на «Параметрах». Ключ удалили → None.
    Bootstrap-окно (`account_id=None`) читает `app_settings.updated_at`; нет PG/строки → None.
    """
    try:
        if account_id is None:
            executor = db or get_pool()
            row = await executor.fetchrow(
                "select updated_at from app_settings where key = $1", "openrouter_api_key"
            )
        elif db is not None:
            row = await db.fetchrow(
                "select updated_at from account_settings where account_id = $1 and key = $2",
                account_id,
                "openrouter_api_key",
            )
        else:
            async with account_scope(account_id) as scoped:
                row = await scoped.fetchrow(
                    "select updated_at from account_settings where account_id = $1 and key = $2",
                    account_id,
                    "openrouter_api_key",
                )
    except Exception as exc:
        logger.debug(
            "settings: чтение updated_at openrouter_api_key (account_id=%s) недоступно: %s",
            account_id,
            exc,
        )
        return None
    if row is None:
        return None
    return row["updated_at"]


async def load_openrouter_key_into_runtime(
    *, account_id: int | None, db: Executor | None = None
) -> None:
    """Положить ключ OpenRouter из БД в in-process holder ядра (core.config).

    Вызывается на старте API (lifespan): ключ, введённый на странице «Параметры», начинает
    действовать сразу, без правки .env. Путь друга — вставил ключ на фронте, перезапустил (или
    даже без рестарта: PATCH тоже обновляет holder), всё работает. Пусто в БД → holder сброшен
    (фолбэк на OPENROUTER_API_KEY из .env, путь владельца). PG недоступен — тихий no-op.

    `account_id` — Этап 2 держит один процесс-holder на инсталляцию (product остаётся
    де-факто однопользовательским до Этапа 5): вызывающая сторона передаёт владельца
    (`core.platform.repo.accounts.resolve_default_account_id`), не произвольный аккаунт.
    """
    from core.config import set_runtime_openrouter_key

    stored = await get_setting("openrouter_api_key", default=None, account_id=account_id, db=db)
    set_runtime_openrouter_key(stored if isinstance(stored, str) else None)


async def prime_runtime_openrouter_key_for_account(
    account_id: int, *, db: Executor | None = None
) -> None:
    """Обновить per-request кэш ключа OpenRouter для `account_id`, если он протух (TTL 15с,
    `core.platform.config.runtime.account_openrouter_key_cache_stale`) — Этап 5 fix: LLM-вызовы
    внутри запроса/апдейта этого аккаунта обязаны видеть ЕГО ключ, не ключ владельца/последнего
    сохранившего (см. память project_openrouter_key_flow_2026_08_05). Зовётся из
    `api.security.require_account(_context)` на каждый HTTP-запрос и из account-middleware
    бота на каждый апдейт — дёшево при тёплом кэше (только сравнение времени, без SELECT).
    """
    from core.config import account_openrouter_key_cache_stale, cache_account_openrouter_key

    if not account_openrouter_key_cache_stale(account_id):
        return
    stored = await get_setting("openrouter_api_key", default=None, account_id=account_id, db=db)
    cache_account_openrouter_key(account_id, stored if isinstance(stored, str) else None)


__all__ = [
    "DEFAULT_COMPANY_ADJUSTMENTS",
    "DEFAULT_SCORING_IMPORTANCE",
    "DEFAULT_SCORING_WEIGHTS",
    "KEY_ONBOARDING",
    "get_extension_version",
    "get_openrouter_key_set_at",
    "get_runner_tick",
    "get_setting",
    "is_extension_confirmed",
    "is_openrouter_key_configured",
    "load_openrouter_key_into_runtime",
    "prime_runtime_openrouter_key_for_account",
    "record_runner_tick",
    "set_extension_confirmed",
    "set_extension_version",
    "set_setting",
    "should_log_runner_tick",
]
