"""Происхождение действующего ключа OpenRouter (таблица `openrouter_account_keys`, 0141).

Две стороны, два пути к БД — как в `core.platform.repo.openrouter_key_requests`:

- владелец ключа читает СВОЮ строку через `account_scope()` (RLS, обычный путь);
- оператор пишет чужую строку и читает весь флот — МИМО `account_scope()` (соединение по
  умолчанию — владелец таблиц, обходит RLS).

Секрет здесь не хранится: только маска, метка и кто/когда выдал. Сам ключ — в
`account_settings.openrouter_api_key`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

Origin = Literal["self", "admin"]

_COLUMNS = "account_id, origin, key_hint, label, issued_by, issued_at, updated_at"


@dataclass(frozen=True, slots=True)
class KeyOriginRecord:
    """Строка `openrouter_account_keys` — метаданные действующего ключа аккаунта."""

    account_id: int
    origin: Origin
    key_hint: str
    label: str | None
    issued_by: int | None
    issued_at: datetime
    updated_at: datetime


def _record_from_row(row: object) -> KeyOriginRecord | None:
    if row is None:
        return None
    return KeyOriginRecord(**row_to_dict(row))  # type: ignore[arg-type]


async def get_origin(account_id: int, *, db: Executor | None = None) -> KeyOriginRecord | None:
    """Своя строка — через `account_scope()` (путь владельца ключа, «Аккаунт»).

    Чтение терпимо к лежащему PG (как `repo.settings.get_setting`): «Аккаунт» и так отдаёт
    остальные поля из дефолтов, и падать 500 из-за декоративной подписи «кто выдал» нельзя.
    """
    try:
        if db is not None:
            row = await db.fetchrow(
                f"select {_COLUMNS} from openrouter_account_keys where account_id = $1", account_id
            )
        else:
            async with account_scope(account_id) as scoped:
                row = await scoped.fetchrow(
                    f"select {_COLUMNS} from openrouter_account_keys where account_id = $1",
                    account_id,
                )
    except Exception as exc:
        logger.debug(
            "openrouter_account_keys: чтение account_id=%s недоступно: %s", account_id, exc
        )
        return None
    return _record_from_row(row)


async def upsert_origin(
    account_id: int,
    *,
    origin: Origin,
    key_hint: str,
    label: str | None = None,
    issued_by: int | None = None,
    db: Executor | None = None,
) -> None:
    """Записать происхождение нового ключа. Мимо RLS: оператор пишет чужую строку.

    `issued_at` не переписывается при повторной выдаче тем же оператором — дата первой выдачи
    полезнее в консоли, чем дата последней правки метки; «когда трогали» несёт `updated_at`.
    """
    executor = db or get_pool()
    await executor.execute(
        "insert into openrouter_account_keys "
        "(account_id, origin, key_hint, label, issued_by, issued_at, updated_at) "
        "values ($1, $2, $3, $4, $5, now(), now()) "
        "on conflict (account_id) do update set "
        "origin = excluded.origin, key_hint = excluded.key_hint, label = excluded.label, "
        "issued_by = excluded.issued_by, issued_at = now(), updated_at = now()",
        account_id,
        origin,
        key_hint,
        label,
        issued_by,
    )


async def delete_origin(account_id: int, *, db: Executor | None = None) -> None:
    """Ключа больше нет — метаданные тоже уходят (строка живёт ровно пока живёт ключ)."""
    executor = db or get_pool()
    await executor.execute("delete from openrouter_account_keys where account_id = $1", account_id)


async def list_origins(*, db: Executor | None = None) -> list[KeyOriginRecord]:
    """Весь флот — для операторской консоли (кросс-аккаунтный список, мимо RLS)."""
    try:
        executor = db or get_pool()
        rows = await executor.fetch(f"select {_COLUMNS} from openrouter_account_keys")
    except Exception as exc:
        logger.debug("openrouter_account_keys: список недоступен: %s", exc)
        return []
    return [KeyOriginRecord(**row_to_dict(row)) for row in rows]


__all__ = [
    "KeyOriginRecord",
    "Origin",
    "delete_origin",
    "get_origin",
    "list_origins",
    "upsert_origin",
]
