"""Хранилище очереди: Postgres (прод) и память (тесты / PG недоступен)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from core.platform.db.pool import TimingPool, row_to_dict
from core.platform.tasks.models import TaskRecord, TaskStatus

TASK_REASON_LEN = 120


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _row_to_task(row: dict[str, Any]) -> TaskRecord:
    return TaskRecord.model_validate(row)


def _rowcount(status: object) -> int:
    """asyncpg `execute` возвращает «UPDATE N» / «DELETE N»."""
    try:
        return int(str(status).split()[-1])
    except (ValueError, IndexError):
        return 0


@runtime_checkable
class TaskStore(Protocol):
    async def enqueue(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        priority: int,
        idempotency_key: str | None,
        run_at: datetime,
        max_attempts: int,
        account_id: int | None = None,
    ) -> TaskRecord: ...

    async def claim_next(self, kinds: Sequence[str] | None = None) -> TaskRecord | None: ...

    async def mark_done(self, task_id: int) -> None: ...

    async def mark_retry_or_fail(
        self, task_id: int, *, error: str, backoff_sec: float
    ) -> TaskStatus: ...

    async def reclaim_stuck(self) -> int: ...

    async def retry_task(self, task_id: int) -> TaskRecord | None: ...

    async def cancel_task(self, task_id: int) -> TaskRecord | None: ...

    async def retry_failed_of_kind(self, kind: str, *, reason: str = "") -> int: ...

    async def cancel_failed_of_kind(self, kind: str, *, reason: str = "") -> int: ...

    async def list_recent(
        self, *, limit: int = 50, account_id: int | None = None
    ) -> list[TaskRecord]: ...

    async def has_active(self, idempotency_key: str) -> bool: ...

    async def exists_key(self, idempotency_key: str) -> bool: ...

    async def has_pending_of_kind(self, kind: str) -> bool: ...


class MemoryTaskStore:
    """In-process очередь для тестов и деградации без Postgres."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._seq = 0
        self._rows: dict[int, TaskRecord] = {}

    async def enqueue(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        priority: int,
        idempotency_key: str | None,
        run_at: datetime,
        max_attempts: int,
        account_id: int | None = None,
    ) -> TaskRecord:
        async with self._lock:
            if idempotency_key:
                for row in self._rows.values():
                    if row.idempotency_key == idempotency_key and row.status in (
                        TaskStatus.PENDING,
                        TaskStatus.RUNNING,
                    ):
                        return row
            self._seq += 1
            now = _utcnow()
            task = TaskRecord(
                id=self._seq,
                kind=kind,
                idempotency_key=idempotency_key,
                priority=priority,
                payload=dict(payload),
                account_id=account_id,
                status=TaskStatus.PENDING,
                attempts=0,
                max_attempts=max_attempts,
                run_at=run_at if run_at.tzinfo else run_at.replace(tzinfo=UTC),
                created_at=now,
                updated_at=now,
            )
            self._rows[task.id] = task
            return task

    async def claim_next(self, kinds: Sequence[str] | None = None) -> TaskRecord | None:
        async with self._lock:
            if kinds is not None and len(kinds) == 0:
                return None
            now = _utcnow()
            allowed = set(kinds) if kinds is not None else None
            candidates = [
                t
                for t in self._rows.values()
                if t.status == TaskStatus.PENDING
                and t.run_at <= now
                and (allowed is None or t.kind in allowed)
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda t: (t.priority, t.run_at, t.id))
            picked = candidates[0]
            updated = picked.model_copy(
                update={
                    "status": TaskStatus.RUNNING,
                    "attempts": picked.attempts + 1,
                    "started_at": now,
                    "updated_at": now,
                }
            )
            self._rows[updated.id] = updated
            return updated

    async def mark_done(self, task_id: int) -> None:
        async with self._lock:
            row = self._rows.get(task_id)
            # Отменённую не перезаписываем: оператор мог снять зависшую, пока воркер ещё крутил.
            if row is None or row.status != TaskStatus.RUNNING:
                return
            now = _utcnow()
            self._rows[task_id] = row.model_copy(
                update={
                    "status": TaskStatus.DONE,
                    "finished_at": now,
                    "updated_at": now,
                    "last_error": "",
                }
            )

    async def mark_retry_or_fail(
        self, task_id: int, *, error: str, backoff_sec: float
    ) -> TaskStatus:
        async with self._lock:
            row = self._rows.get(task_id)
            if row is None:
                return TaskStatus.FAILED
            if row.status != TaskStatus.RUNNING:
                return row.status
            now = _utcnow()
            if row.attempts < row.max_attempts:
                status = TaskStatus.PENDING
                self._rows[task_id] = row.model_copy(
                    update={
                        "status": status,
                        "run_at": now + timedelta(seconds=backoff_sec),
                        "started_at": None,
                        "last_error": error[:2000],
                        "updated_at": now,
                    }
                )
                return status
            self._rows[task_id] = row.model_copy(
                update={
                    "status": TaskStatus.FAILED,
                    "finished_at": now,
                    "last_error": error[:2000],
                    "updated_at": now,
                }
            )
            return TaskStatus.FAILED

    async def reclaim_stuck(self) -> int:
        async with self._lock:
            now = _utcnow()
            n = 0
            for tid, row in list(self._rows.items()):
                if row.status == TaskStatus.RUNNING:
                    self._rows[tid] = row.model_copy(
                        update={
                            "status": TaskStatus.PENDING,
                            "started_at": None,
                            "updated_at": now,
                            "run_at": now,
                        }
                    )
                    n += 1
            return n

    async def retry_task(self, task_id: int) -> TaskRecord | None:
        async with self._lock:
            row = self._rows.get(task_id)
            if row is None or row.status not in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                return None
            if row.idempotency_key:
                for other in self._rows.values():
                    if (
                        other.id != row.id
                        and other.idempotency_key == row.idempotency_key
                        and other.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                    ):
                        return None
            now = _utcnow()
            updated = row.model_copy(
                update={
                    "status": TaskStatus.PENDING,
                    "attempts": 0,
                    "last_error": "",
                    "started_at": None,
                    "finished_at": None,
                    "run_at": now,
                    "updated_at": now,
                }
            )
            self._rows[task_id] = updated
            return updated

    async def cancel_task(self, task_id: int) -> TaskRecord | None:
        async with self._lock:
            row = self._rows.get(task_id)
            if row is None or row.status not in (TaskStatus.PENDING, TaskStatus.RUNNING):
                return None
            now = _utcnow()
            updated = row.model_copy(
                update={
                    "status": TaskStatus.CANCELLED,
                    "finished_at": now,
                    "updated_at": now,
                }
            )
            self._rows[task_id] = updated
            return updated

    async def retry_failed_of_kind(self, kind: str, *, reason: str = "") -> int:
        async with self._lock:
            now = _utcnow()
            needle = reason[:TASK_REASON_LEN]
            active_keys = {
                r.idempotency_key
                for r in self._rows.values()
                if r.idempotency_key and r.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            }
            n = 0
            for tid, row in list(self._rows.items()):
                if row.status != TaskStatus.FAILED or row.kind != kind:
                    continue
                if needle and row.last_error[:TASK_REASON_LEN] != needle:
                    continue
                if row.idempotency_key and row.idempotency_key in active_keys:
                    continue
                self._rows[tid] = row.model_copy(
                    update={
                        "status": TaskStatus.PENDING,
                        "attempts": 0,
                        "last_error": "",
                        "started_at": None,
                        "finished_at": None,
                        "run_at": now,
                        "updated_at": now,
                    }
                )
                if row.idempotency_key:
                    active_keys.add(row.idempotency_key)
                n += 1
            return n

    async def cancel_failed_of_kind(self, kind: str, *, reason: str = "") -> int:
        async with self._lock:
            now = _utcnow()
            needle = reason[:TASK_REASON_LEN]
            n = 0
            for tid, row in list(self._rows.items()):
                if row.status != TaskStatus.FAILED or row.kind != kind:
                    continue
                if needle and row.last_error[:TASK_REASON_LEN] != needle:
                    continue
                self._rows[tid] = row.model_copy(
                    update={
                        "status": TaskStatus.CANCELLED,
                        "finished_at": now,
                        "updated_at": now,
                    }
                )
                n += 1
            return n

    async def list_recent(
        self, *, limit: int = 50, account_id: int | None = None
    ) -> list[TaskRecord]:
        async with self._lock:
            rows = sorted(self._rows.values(), key=lambda t: t.created_at, reverse=True)
            if account_id is not None:
                rows = [r for r in rows if r.account_id is None or r.account_id == account_id]
            return rows[: max(1, min(limit, 200))]

    async def has_active(self, idempotency_key: str) -> bool:
        async with self._lock:
            return any(
                r.idempotency_key == idempotency_key
                and r.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                for r in self._rows.values()
            )

    async def exists_key(self, idempotency_key: str) -> bool:
        async with self._lock:
            return any(r.idempotency_key == idempotency_key for r in self._rows.values())

    async def has_pending_of_kind(self, kind: str) -> bool:
        async with self._lock:
            return any(
                r.kind == kind and r.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
                for r in self._rows.values()
            )


class PgTaskStore:
    """Очередь в Postgres — переживает перезапуск процесса."""

    def __init__(self, pool: TimingPool) -> None:
        self._pool = pool

    async def enqueue(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        priority: int,
        idempotency_key: str | None,
        run_at: datetime,
        max_attempts: int,
        account_id: int | None = None,
    ) -> TaskRecord:
        if idempotency_key:
            existing = await self._pool.fetchrow(
                """
                select * from background_tasks
                where idempotency_key = $1
                  and status in ('pending', 'running')
                limit 1
                """,
                idempotency_key,
            )
            if existing is not None:
                return _row_to_task(row_to_dict(existing))

        row = await self._pool.fetchrow(
            """
            insert into background_tasks (
                kind, idempotency_key, priority, payload, run_at, max_attempts, account_id
            ) values ($1, $2, $3, $4::jsonb, $5, $6, $7)
            returning *
            """,
            kind,
            idempotency_key,
            priority,
            payload,
            run_at,
            max_attempts,
            account_id,
        )
        assert row is not None
        return _row_to_task(row_to_dict(row))

    async def claim_next(self, kinds: Sequence[str] | None = None) -> TaskRecord | None:
        if kinds is not None and len(kinds) == 0:
            return None
        kind_filter = list(kinds) if kinds is not None else None
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                with next as (
                    select id
                    from background_tasks
                    where status = 'pending' and run_at <= now()
                      and ($1::text[] is null or kind = any($1::text[]))
                    order by priority asc, run_at asc, id asc
                    for update skip locked
                    limit 1
                )
                update background_tasks t
                set status = 'running',
                    started_at = now(),
                    attempts = attempts + 1,
                    updated_at = now()
                from next
                where t.id = next.id
                returning t.*
                """,
                kind_filter,
            )
        if row is None:
            return None
        return _row_to_task(row_to_dict(row))

    async def mark_done(self, task_id: int) -> None:
        await self._pool.execute(
            """
            update background_tasks
            set status = 'done',
                finished_at = now(),
                last_error = '',
                updated_at = now()
            where id = $1 and status = 'running'
            """,
            task_id,
        )

    async def mark_retry_or_fail(
        self, task_id: int, *, error: str, backoff_sec: float
    ) -> TaskStatus:
        row = await self._pool.fetchrow(
            """
            update background_tasks
            set
                status = case
                    when attempts < max_attempts then 'pending'
                    else 'failed'
                end,
                run_at = case
                    when attempts < max_attempts
                        then now() + make_interval(secs => $2::double precision)
                    else run_at
                end,
                started_at = case
                    when attempts < max_attempts then null
                    else started_at
                end,
                finished_at = case
                    when attempts < max_attempts then null
                    else now()
                end,
                last_error = $3,
                updated_at = now()
            where id = $1 and status = 'running'
            returning status
            """,
            task_id,
            backoff_sec,
            error[:2000],
        )
        if row is None:
            return TaskStatus.FAILED
        return TaskStatus(row["status"])

    async def reclaim_stuck(self) -> int:
        status = await self._pool.execute(
            """
            update background_tasks
            set status = 'pending',
                started_at = null,
                run_at = now(),
                updated_at = now()
            where status = 'running'
            """
        )
        return _rowcount(status)

    async def retry_task(self, task_id: int) -> TaskRecord | None:
        row = await self._pool.fetchrow(
            """
            update background_tasks t
            set status = 'pending',
                attempts = 0,
                last_error = '',
                started_at = null,
                finished_at = null,
                run_at = now(),
                updated_at = now()
            where t.id = $1
              and t.status in ('failed', 'cancelled')
              and (
                t.idempotency_key is null
                or not exists (
                    select 1 from background_tasks x
                    where x.idempotency_key = t.idempotency_key
                      and x.status in ('pending', 'running')
                      and x.id <> t.id
                )
              )
            returning t.*
            """,
            task_id,
        )
        if row is None:
            return None
        return _row_to_task(row_to_dict(row))

    async def cancel_task(self, task_id: int) -> TaskRecord | None:
        row = await self._pool.fetchrow(
            """
            update background_tasks
            set status = 'cancelled',
                finished_at = now(),
                updated_at = now()
            where id = $1 and status in ('pending', 'running')
            returning *
            """,
            task_id,
        )
        if row is None:
            return None
        return _row_to_task(row_to_dict(row))

    async def retry_failed_of_kind(self, kind: str, *, reason: str = "") -> int:
        status = await self._pool.execute(
            """
            update background_tasks t
            set status = 'pending',
                attempts = 0,
                last_error = '',
                started_at = null,
                finished_at = null,
                run_at = now(),
                updated_at = now()
            where t.status = 'failed' and t.kind = $1
              and ($2 = '' or left(t.last_error, $3) = $2)
              and (
                t.idempotency_key is null
                or not exists (
                    select 1 from background_tasks x
                    where x.idempotency_key = t.idempotency_key
                      and x.status in ('pending', 'running')
                )
              )
            """,
            kind,
            reason[:TASK_REASON_LEN],
            TASK_REASON_LEN,
        )
        return _rowcount(status)

    async def cancel_failed_of_kind(self, kind: str, *, reason: str = "") -> int:
        status = await self._pool.execute(
            """
            update background_tasks
            set status = 'cancelled',
                finished_at = now(),
                updated_at = now()
            where status = 'failed' and kind = $1
              and ($2 = '' or left(last_error, $3) = $2)
            """,
            kind,
            reason[:TASK_REASON_LEN],
            TASK_REASON_LEN,
        )
        return _rowcount(status)

    async def list_recent(
        self, *, limit: int = 50, account_id: int | None = None
    ) -> list[TaskRecord]:
        if account_id is None:
            rows = await self._pool.fetch(
                """
                select * from background_tasks
                order by created_at desc
                limit $1
                """,
                max(1, min(limit, 200)),
            )
        else:
            # Свои задачи + системные (account_id is null) — не чужие.
            rows = await self._pool.fetch(
                """
                select * from background_tasks
                where account_id is null or account_id = $2
                order by created_at desc
                limit $1
                """,
                max(1, min(limit, 200)),
                account_id,
            )
        return [_row_to_task(row_to_dict(r)) for r in rows]

    async def has_active(self, idempotency_key: str) -> bool:
        val = await self._pool.fetchval(
            """
            select exists(
                select 1 from background_tasks
                where idempotency_key = $1
                  and status in ('pending', 'running')
            )
            """,
            idempotency_key,
        )
        return bool(val)

    async def exists_key(self, idempotency_key: str) -> bool:
        val = await self._pool.fetchval(
            """
            select exists(
                select 1 from background_tasks where idempotency_key = $1
            )
            """,
            idempotency_key,
        )
        return bool(val)

    async def has_pending_of_kind(self, kind: str) -> bool:
        val = await self._pool.fetchval(
            """
            select exists(
                select 1 from background_tasks
                where kind = $1 and status in ('pending', 'running')
            )
            """,
            kind,
        )
        return bool(val)


__all__ = ["MemoryTaskStore", "PgTaskStore", "TaskStore"]
