"""Этап 7: retry возвращает pending со сброшенным attempts, cancel не трогает done,
purge удаляет строго старше окна и пишет аудит."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.platform.admin.models import AdminError
from core.platform.admin.service import (
    cancel_task,
    load_tasks,
    purge_logs,
    reclaim_stuck_tasks,
    retry_failed_of_kind,
    retry_task,
)
from core.platform.tasks import MemoryTaskStore, TaskStatus, reset_runtime_for_tests
from core.platform.tasks.runtime import TaskRuntime


@pytest.fixture
def runtime() -> TaskRuntime:
    return reset_runtime_for_tests(MemoryTaskStore())


async def _fail(runtime: TaskRuntime, kind: str = "demo", **kwargs: Any):
    """enqueue → claim → исчерпать попытки → failed."""
    task = await runtime.enqueue(kind, max_attempts=1, **kwargs)
    claimed = await runtime.store.claim_next()
    assert claimed is not None and claimed.id == task.id
    status = await runtime.store.mark_retry_or_fail(claimed.id, error="boom", backoff_sec=0)
    assert status == TaskStatus.FAILED
    return claimed.id


@pytest.mark.asyncio
async def test_retry_returns_pending_with_reset_attempts(runtime: TaskRuntime) -> None:
    task_id = await _fail(runtime, "tg_push")
    record = await runtime.retry_task(task_id)
    assert record is not None
    assert record.status == TaskStatus.PENDING
    assert record.attempts == 0
    assert record.last_error == ""
    assert record.started_at is None
    assert record.finished_at is None


@pytest.mark.asyncio
async def test_retry_does_not_touch_done(runtime: TaskRuntime) -> None:
    task = await runtime.enqueue("demo", max_attempts=1)
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    await runtime.store.mark_done(claimed.id)
    assert await runtime.retry_task(task.id) is None
    rows = await runtime.list_recent()
    assert next(r for r in rows if r.id == task.id).status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_cancel_pending_and_running(runtime: TaskRuntime) -> None:
    first = await runtime.enqueue("a")
    second = await runtime.enqueue("b")
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    leftover_id = second.id if claimed.id == first.id else first.id
    cancelled_running = await runtime.cancel_task(claimed.id)
    cancelled_pending = await runtime.cancel_task(leftover_id)
    assert cancelled_running is not None and cancelled_running.status == TaskStatus.CANCELLED
    assert cancelled_pending is not None and cancelled_pending.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_does_not_touch_done(runtime: TaskRuntime) -> None:
    task = await runtime.enqueue("demo")
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    await runtime.store.mark_done(claimed.id)
    assert await runtime.cancel_task(task.id) is None
    rows = await runtime.list_recent()
    assert next(r for r in rows if r.id == task.id).status == TaskStatus.DONE


@pytest.mark.asyncio
async def test_cancel_does_not_touch_failed(runtime: TaskRuntime) -> None:
    task_id = await _fail(runtime)
    assert await runtime.cancel_task(task_id) is None


@pytest.mark.asyncio
async def test_mark_done_after_cancel_stays_cancelled(runtime: TaskRuntime) -> None:
    """Воркер докрутил отменённую — статус не должен вернуться в done."""
    task = await runtime.enqueue("demo")
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    await runtime.cancel_task(claimed.id)
    await runtime.store.mark_done(claimed.id)
    rows = await runtime.list_recent()
    assert next(r for r in rows if r.id == task.id).status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_retry_failed_of_kind_only_that_kind(runtime: TaskRuntime) -> None:
    push = await _fail(runtime, "tg_push")
    salary = await _fail(runtime, "salary_estimate")
    n = await runtime.retry_failed_of_kind("tg_push")
    assert n == 1
    rows = {r.id: r for r in await runtime.list_recent()}
    assert rows[push].status == TaskStatus.PENDING
    assert rows[push].attempts == 0
    assert rows[salary].status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_reclaim_unsticks_running(runtime: TaskRuntime) -> None:
    task = await runtime.enqueue("demo")
    claimed = await runtime.store.claim_next()
    assert claimed is not None and claimed.status == TaskStatus.RUNNING
    n = await runtime.reclaim_stuck()
    assert n == 1
    rows = await runtime.list_recent()
    row = next(r for r in rows if r.id == task.id)
    assert row.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_admin_retry_writes_audit(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[dict[str, object]] = []

    async def fake_record(**kwargs: object) -> None:
        recorded.append(kwargs)

    import core.platform.admin.service as admin_svc

    monkeypatch.setattr(admin_svc, "record_audit", fake_record)
    task_id = await _fail(runtime, "tg_push", account_id=7)
    detail = await retry_task(task_id, actor_id=1)
    assert detail.status == "pending"
    assert detail.attempts == 0
    assert recorded[0]["action"] == "task_retry"
    assert recorded[0]["target_id"] == 7
    assert recorded[0]["details"]["task_id"] == task_id


@pytest.mark.asyncio
async def test_admin_cancel_done_raises(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.platform.admin.service as admin_svc

    monkeypatch.setattr(admin_svc, "record_audit", AsyncMock())
    task = await runtime.enqueue("demo")
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    await runtime.store.mark_done(claimed.id)
    with pytest.raises(AdminError, match="отменить"):
        await cancel_task(task.id, actor_id=1)


@pytest.mark.asyncio
async def test_admin_retry_kind_and_reclaim_audit(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[dict[str, object]] = []

    async def fake_record(**kwargs: object) -> None:
        recorded.append(kwargs)

    import core.platform.admin.service as admin_svc

    monkeypatch.setattr(admin_svc, "record_audit", fake_record)
    await _fail(runtime, "tg_push")
    await _fail(runtime, "tg_push")
    n = await retry_failed_of_kind("tg_push", actor_id=1)
    assert n == 2
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    reclaimed = await reclaim_stuck_tasks(actor_id=1)
    assert reclaimed == 1
    actions = [row["action"] for row in recorded]
    assert actions == ["task_retry", "task_reclaim"]
    assert recorded[0]["details"]["kind"] == "tg_push"
    assert recorded[0]["details"]["n"] == 2


@pytest.mark.asyncio
async def test_purge_deletes_older_than_window_and_writes_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[dict[str, object]] = []

    async def fake_record(**kwargs: object) -> None:
        recorded.append(kwargs)

    class _Pool:
        sql = ""
        args: tuple[Any, ...] = ()

        async def execute(self, sql: str, *args: Any) -> str:
            self.sql = sql
            self.args = args
            return "DELETE 4"

    pool = _Pool()
    import core.platform.admin.service as admin_svc

    monkeypatch.setattr(admin_svc, "get_pool", lambda: pool)
    monkeypatch.setattr(admin_svc, "record_audit", fake_record)

    n = await purge_logs(days=30, actor_id=1)
    assert n == 4
    assert "delete from copilot_logs" in pool.sql.lower()
    assert "ts < now()" in pool.sql
    assert pool.args == (30,)
    assert recorded[0]["action"] == "logs_purge"
    assert recorded[0]["details"]["days"] == 30
    assert recorded[0]["details"]["deleted"] == 4
    assert recorded[0]["target_id"] is None


@pytest.mark.asyncio
async def test_purge_rejects_window_outside_30_60_90(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.platform.admin.service as admin_svc

    monkeypatch.setattr(admin_svc, "record_audit", AsyncMock())
    with pytest.raises(AdminError, match="30, 60 или 90"):
        await purge_logs(days=7, actor_id=1)
    with pytest.raises(AdminError, match="30, 60 или 90"):
        await purge_logs(days=365, actor_id=1)


@pytest.mark.asyncio
async def test_load_tasks_filters_by_status_and_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.platform.admin.service as admin_svc

    captured: list[tuple[str, tuple[Any, ...]]] = []

    async def fake_fetch(sql: str, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        _ = kwargs
        captured.append((sql, args))
        if "order by n desc" in sql:
            return [
                {
                    "kind": "tg_push",
                    "status": "failed",
                    "reason": "boom",
                    "n": 2,
                    "last_finished_at": None,
                    "first_finished_at": None,
                }
            ]
        if "group by kind, status" in sql:
            return [{"kind": "tg_push", "status": "failed", "n": 2}]
        if "group by status" in sql:
            return [{"status": "failed", "n": 2}, {"status": "done", "n": 5}]
        now = datetime.now(UTC)
        return [
            {
                "id": 9,
                "kind": "tg_push",
                "account_id": None,
                "status": "failed",
                "payload": {"text": "hi"},
                "attempts": 3,
                "max_attempts": 3,
                "last_error": "boom",
                "priority": 40,
                "idempotency_key": None,
                "run_at": now,
                "started_at": None,
                "finished_at": now - timedelta(minutes=1),
                "created_at": now,
                "updated_at": now,
                "total_count": 2,
            }
        ]

    async def fake_fetchrow(sql: str, *args: Any, **kwargs: Any) -> dict[str, Any] | None:
        _ = sql, args, kwargs
        return {"n": 1}

    monkeypatch.setattr(admin_svc, "_fetch", fake_fetch)
    monkeypatch.setattr(admin_svc, "_fetchrow", fake_fetchrow)
    page = await load_tasks(status="failed", kind="tg_push", limit=20)
    assert page.by_status.failed == 2
    assert page.by_status.done == 5
    assert page.by_kind[0].kind == "tg_push"
    assert page.by_kind[0].failed == 2
    assert page.items[0].payload == {"text": "hi"}
    assert page.total == 2
    assert page.reasons_total == 1
    list_sql, list_args = next(c for c in captured if "from background_tasks t" in c[0])
    assert "tg_push" not in list_sql
    # окно 48ч + status + kind + item_cap (max(20*5, 20) = 100)
    assert list_args == (48, "failed", "tg_push", 100)
