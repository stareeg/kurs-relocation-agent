"""BYOK-заявки на ключ OpenRouter.

Две стороны, два пути к БД (см. докстринг миграции 0099_openrouter_key_requests.sql):

- заявитель создаёт/читает СВОЮ заявку — через `account_scope()` (RLS, обычный путь);
- оператор видит все pending-заявки и резолвит чужую — идёт МИМО `account_scope()`, тем же
  приёмом, что `core.platform.repo.accounts` (соединение по умолчанию — владелец таблиц,
  обходит RLS; тот же класс операций, что системные подключения `app_admin`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

Status = Literal["pending", "approved", "rejected", "fulfilled"]

_COLUMNS = "id, account_id, status, requested_at, resolved_at, resolved_by, note"


@dataclass(frozen=True, slots=True)
class OpenRouterKeyRequestRecord:
    """Строка `openrouter_key_requests`."""

    id: int
    account_id: int
    status: Status
    requested_at: datetime
    resolved_at: datetime | None
    resolved_by: int | None
    note: str | None


def _record_from_row(row: object) -> OpenRouterKeyRequestRecord | None:
    if row is None:
        return None
    return OpenRouterKeyRequestRecord(**row_to_dict(row))  # type: ignore[arg-type]


# --- Заявитель (account_scope, RLS) ---


async def get_own_pending_request(
    account_id: int, *, db: Executor | None = None
) -> OpenRouterKeyRequestRecord | None:
    """Своя незакрытая заявка (pending/approved) — не даём наплодить дубликаты кликами."""
    if db is not None:
        row = await db.fetchrow(
            f"select {_COLUMNS} from openrouter_key_requests "
            "where account_id = $1 and status in ('pending', 'approved') "
            "order by requested_at desc limit 1",
            account_id,
        )
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(
                f"select {_COLUMNS} from openrouter_key_requests "
                "where account_id = $1 and status in ('pending', 'approved') "
                "order by requested_at desc limit 1",
                account_id,
            )
    return _record_from_row(row)


async def get_own_latest_request(
    account_id: int, *, db: Executor | None = None
) -> OpenRouterKeyRequestRecord | None:
    """Последняя заявка любого статуса — «Аккаунт» показывает по ней, что стало с запросом
    (в работе / отклонена), а не только «есть ли незакрытая»."""
    sql = (
        f"select {_COLUMNS} from openrouter_key_requests "
        "where account_id = $1 order by requested_at desc limit 1"
    )
    # Терпимо к лежащему PG: статус заявки — подпись на «Аккаунте», из-за неё страница
    # настроек падать не должна (тот же приём, что `repo.settings.get_setting`).
    try:
        if db is not None:
            row = await db.fetchrow(sql, account_id)
        else:
            async with account_scope(account_id) as scoped:
                row = await scoped.fetchrow(sql, account_id)
    except Exception as exc:
        logger.debug(
            "openrouter_key_requests: заявка account_id=%s недоступна: %s", account_id, exc
        )
        return None
    return _record_from_row(row)


async def create_request(
    account_id: int, *, db: Executor | None = None
) -> OpenRouterKeyRequestRecord:
    """Новая заявка (не проверяет дубликаты — вызывающая сторона зовёт `get_own_pending_request`
    первой, см. `core.platform.openrouter_keys.request_key`)."""
    if db is not None:
        row = await db.fetchrow(
            f"insert into openrouter_key_requests (account_id) values ($1) returning {_COLUMNS}",
            account_id,
        )
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(
                f"insert into openrouter_key_requests (account_id) values ($1) "
                f"returning {_COLUMNS}",
                account_id,
            )
    record = _record_from_row(row)
    assert record is not None  # insert ... returning всегда отдаёт строку
    return record


# --- Оператор (мимо account_scope — кросс-аккаунтный доступ) ---


async def get_request(
    request_id: int, *, db: Executor | None = None
) -> OpenRouterKeyRequestRecord | None:
    executor = db or get_pool()
    row = await executor.fetchrow(
        f"select {_COLUMNS} from openrouter_key_requests where id = $1", request_id
    )
    return _record_from_row(row)


async def close_open_requests(
    account_id: int,
    *,
    status: Literal["fulfilled", "rejected"],
    resolved_by: int,
    note: str | None = None,
    db: Executor | None = None,
) -> int:
    """Закрыть все незакрытые заявки аккаунта одним статусом; возвращает число закрытых.

    Оператор выдаёт ключ по account_id, а не по id заявки (`openrouter_keys.issue_key`) —
    висящая заявка того же человека обязана закрыться сама, иначе очередь в консоли копит
    строки, по которым уже всё сделано.
    """
    executor = db or get_pool()
    rows = await executor.fetch(
        "update openrouter_key_requests set status = $2, resolved_at = now(), "
        "resolved_by = $3, note = coalesce($4, note) "
        "where account_id = $1 and status in ('pending', 'approved') returning id",
        account_id,
        status,
        resolved_by,
        note,
    )
    return len(rows)


__all__ = [
    "OpenRouterKeyRequestRecord",
    "Status",
    "close_open_requests",
    "create_request",
    "get_own_latest_request",
    "get_own_pending_request",
    "get_request",
]
