"""Repository запусков агента и потока событий (A-3).

Запуск живёт фоновой задачей API, но его состояние — в Postgres: статус и события
переживают перезапуск, SSE читает догоном по `id` (Last-Event-ID), пауза на
подтверждении продолжается с чекпойнта графа из нового процесса.

События пишутся с `account_id` (RLS) и монотонным `id` — курсор для переподключения.
Как и у остальных repo: `db=None` → соединение через `account_scope()` (fail-closed),
переданный `db` (транзакция/тест) используется напрямую.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("queued", "running", "waiting_approval")
"""Статусы незавершённого запуска. `running`/`queued` после рестарта — мёртвые задачи."""

_RUN_COLUMNS = (
    "id, account_id, session_id, goal, status, thread_id, stop_reason, answer, error,"
    " created_at, updated_at"
)


@dataclass(frozen=True, slots=True)
class AgentRunRecord:
    """Строка `agent_runs`. Задача графа живёт в памяти процесса, запись — здесь."""

    id: int
    account_id: int
    goal: str
    status: str
    thread_id: str
    session_id: int | None = None
    stop_reason: str | None = None
    answer: str | None = None
    error: str | None = None
    created_at: Any = None
    updated_at: Any = None


@dataclass(frozen=True, slots=True)
class AgentEventRecord:
    """Событие запуска: тип, payload, узел и время узла (таймеры OQ-29)."""

    id: int
    run_id: int
    type: str
    payload: dict[str, Any]
    node: str | None = None
    duration_ms: float | None = None
    created_at: Any = None


def _run_from_row(row: Any) -> AgentRunRecord | None:
    if row is None:
        return None
    data = row_to_dict(row)
    return AgentRunRecord(
        id=int(data["id"]),
        account_id=int(data["account_id"]),
        goal=str(data["goal"]),
        status=str(data["status"]),
        thread_id=str(data["thread_id"]),
        session_id=int(data["session_id"]) if data.get("session_id") is not None else None,
        stop_reason=data.get("stop_reason"),
        answer=data.get("answer"),
        error=data.get("error"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _event_from_row(row: Any) -> AgentEventRecord:
    data = row_to_dict(row)
    return AgentEventRecord(
        id=int(data["id"]),
        run_id=int(data["run_id"]),
        type=str(data["type"]),
        payload=data.get("payload") or {},
        node=data.get("node"),
        duration_ms=data.get("duration_ms"),
        created_at=data.get("created_at"),
    )


async def create_run(
    *,
    account_id: int,
    goal: str,
    thread_id: str,
    session_id: int | None = None,
    db: Executor | None = None,
) -> AgentRunRecord:
    """Создать запуск со статусом `queued`. Возвращает запись с id."""
    if db is not None:
        row = await db.fetchrow(
            "insert into agent_runs (account_id, session_id, goal, thread_id, status)"
            " values ($1, $2, $3, $4, 'queued') returning " + _RUN_COLUMNS,
            account_id,
            session_id,
            goal,
            thread_id,
        )
        run = _run_from_row(row)
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(
                "insert into agent_runs (account_id, session_id, goal, thread_id, status)"
                " values ($1, $2, $3, $4, 'queued') returning " + _RUN_COLUMNS,
                account_id,
                session_id,
                goal,
                thread_id,
            )
        run = _run_from_row(row)
    assert run is not None  # insert … returning всегда даёт строку
    return run


async def get_run(
    run_id: int, *, account_id: int, db: Executor | None = None
) -> AgentRunRecord | None:
    """Запуск аккаунта по id; чужой/несуществующий — None (роутер отвечает 404)."""
    if db is not None:
        row = await db.fetchrow(
            "select " + _RUN_COLUMNS + " from agent_runs where id = $1 and account_id = $2",
            run_id,
            account_id,
        )
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(
                "select " + _RUN_COLUMNS + " from agent_runs where id = $1 and account_id = $2",
                run_id,
                account_id,
            )
    return _run_from_row(row)


async def update_run(
    run_id: int,
    *,
    account_id: int,
    status: str | None = None,
    stop_reason: str | None = None,
    answer: str | None = None,
    error: str | None = None,
    db: Executor | None = None,
) -> AgentRunRecord | None:
    """Патч полей запуска; `updated_at` трогается всегда. None-аргументы не меняются."""
    sets = ["updated_at = now()"]
    values: list[Any] = []
    for column, value in (
        ("status", status),
        ("stop_reason", stop_reason),
        ("answer", answer),
        ("error", error),
    ):
        if value is not None:
            values.append(value)
            sets.append(f"{column} = ${len(values)}")
    values.extend([run_id, account_id])
    where_id, where_account = len(values) - 1, len(values)
    sql = (
        f"update agent_runs set {', '.join(sets)} where id = ${where_id}"
        f" and account_id = ${where_account} returning " + _RUN_COLUMNS
    )
    if db is not None:
        row = await db.fetchrow(sql, *values)
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(sql, *values)
    return _run_from_row(row)


async def list_runs(
    *,
    account_id: int,
    session_id: int | None = None,
    limit: int = 50,
    db: Executor | None = None,
) -> list[AgentRunRecord]:
    """Свежие запуски аккаунта (опционально одной чат-сессии)."""
    if session_id is not None:
        sql = (
            "select " + _RUN_COLUMNS + " from agent_runs where account_id = $1 and session_id = $2"
            " order by created_at desc, id desc limit $3"
        )
        args: tuple[Any, ...] = (account_id, session_id, limit)
    else:
        sql = (
            "select " + _RUN_COLUMNS + " from agent_runs where account_id = $1"
            " order by created_at desc, id desc limit $2"
        )
        args = (account_id, limit)
    if db is not None:
        rows = await db.fetch(sql, *args)
    else:
        async with account_scope(account_id) as scoped:
            rows = await scoped.fetch(sql, *args)
    return [record for row in rows if (record := _run_from_row(row)) is not None]


async def append_event(
    *,
    run_id: int,
    account_id: int,
    type: str,  # noqa: A002 — имя колонки; ключевое слово здесь осознанное
    payload: dict[str, Any],
    node: str | None = None,
    duration_ms: float | None = None,
    db: Executor | None = None,
) -> int:
    """Записать событие и вернуть его монотонный id (курсор SSE)."""
    if db is not None:
        raw = await db.fetchval(
            "insert into agent_events (run_id, account_id, type, payload, node, duration_ms)"
            " values ($1, $2, $3, $4, $5, $6) returning id",
            run_id,
            account_id,
            type,
            payload,
            node,
            duration_ms,
        )
    else:
        async with account_scope(account_id) as scoped:
            raw = await scoped.fetchval(
                "insert into agent_events (run_id, account_id, type, payload, node, duration_ms)"
                " values ($1, $2, $3, $4, $5, $6) returning id",
                run_id,
                account_id,
                type,
                payload,
                node,
                duration_ms,
            )
    return int(raw)


async def list_events(
    *,
    run_id: int,
    account_id: int,
    after_id: int = 0,
    limit: int = 500,
    db: Executor | None = None,
) -> list[AgentEventRecord]:
    """События запуска с id больше `after_id` (догон SSE и восстановление экрана)."""
    if db is not None:
        rows = await db.fetch(
            "select id, run_id, type, payload, node, duration_ms, created_at"
            " from agent_events where run_id = $1 and account_id = $2 and id > $3"
            " order by id limit $4",
            run_id,
            account_id,
            after_id,
            limit,
        )
    else:
        async with account_scope(account_id) as scoped:
            rows = await scoped.fetch(
                "select id, run_id, type, payload, node, duration_ms, created_at"
                " from agent_events where run_id = $1 and account_id = $2 and id > $3"
                " order by id limit $4",
                run_id,
                account_id,
                after_id,
                limit,
            )
    return [_event_from_row(row) for row in rows]


async def mark_stale_failed(reason: str, *, db: Executor | None = None) -> int:
    """При старте API: незакрытые `running`/`queued` — задачи прошлого процесса, fail честно.

    `waiting_approval` не трогаем: пауза на «да» живёт в чекпойнте и продолжается
    (критерий A-3). Вызывается один раз из lifespan, владельцем таблицы (без RLS-скоупа).
    """
    executor = db or get_pool()
    raw = await executor.fetchval(
        "with stale as ("
        "update agent_runs set status = 'failed', error = $1, updated_at = now()"
        " where status in ('running', 'queued') returning 1)"
        " select count(*) from stale",
        reason,
    )
    return int(raw or 0)


__all__ = [
    "OPEN_STATUSES",
    "AgentEventRecord",
    "AgentRunRecord",
    "append_event",
    "create_run",
    "get_run",
    "list_events",
    "list_runs",
    "mark_stale_failed",
    "update_run",
]
