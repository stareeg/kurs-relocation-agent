"""Группировка очереди по (вид, статус, причина) и пачка отмены."""

from __future__ import annotations

from typing import Any

import pytest

import core.platform.admin.service as admin_svc
from core.platform.admin import cancel_failed_of_kind, load_tasks
from core.platform.admin.service import TASK_WINDOW_HOURS
from core.platform.tasks import MemoryTaskStore, TaskStatus, reset_runtime_for_tests
from core.platform.tasks.runtime import TaskRuntime
from core.platform.tasks.store import TASK_REASON_LEN


class _RecordingPool:
    def __init__(self, rows: dict[str, Any] | None = None) -> None:
        self.rows = rows or {}
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def _resolve(self, sql: str) -> Any:
        self.queries.append((sql, ()))
        for marker, value in self.rows.items():
            if marker in sql:
                return value
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        value = self._resolve(sql)
        self.queries[-1] = (sql, args)
        return list(value or [])

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        value = self._resolve(sql)
        self.queries[-1] = (sql, args)
        return dict(value) if isinstance(value, dict) else None

    def args_for(self, marker: str) -> tuple[Any, ...]:
        for sql, args in self.queries:
            if marker in sql:
                return args
        raise AssertionError(f"нет запроса с {marker!r}")


@pytest.mark.asyncio
async def test_load_tasks_groups_by_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = _RecordingPool(
        {
            # Порядок маркеров важен: более узкие — раньше, иначе ") groups" поймает
            # «group by kind, status» из подзапроса числа групп.
            ") groups": {"n": 1},
            "order by n desc, kind, status, reason": [
                {
                    "kind": "tg_cleanup",
                    "status": "failed",
                    "reason": "нет обработчика kind='tg_cleanup'",
                    "n": 2,
                    "last_finished_at": None,
                    "first_finished_at": None,
                }
            ],
            "group by status": [{"status": "failed", "n": 2}],
            "group by kind, status": [{"kind": "tg_cleanup", "status": "failed", "n": 2}],
            "total_count": [
                {
                    "id": 1,
                    "kind": "tg_cleanup",
                    "status": "failed",
                    "payload": {},
                    "attempts": 3,
                    "max_attempts": 3,
                    "last_error": "нет обработчика kind='tg_cleanup'",
                    "priority": 100,
                    "total_count": 2,
                }
            ],
        }
    )
    monkeypatch.setattr(admin_svc, "get_pool", lambda: pool)
    page = await load_tasks(status="failed")
    assert page.by_reason[0].kind == "tg_cleanup"
    assert page.by_reason[0].status == "failed"
    assert page.by_reason[0].count == 2
    assert page.reasons_total == 1
    assert "нет обработчика" in page.by_reason[0].reason
    args = pool.args_for("order by n desc, kind, status, reason")
    assert TASK_WINDOW_HOURS in args
    assert TASK_REASON_LEN in args


@pytest.fixture
def runtime() -> TaskRuntime:
    return reset_runtime_for_tests(MemoryTaskStore())


async def _fail(runtime: TaskRuntime, kind: str, error: str) -> None:
    await runtime.enqueue(kind, max_attempts=1)
    claimed = await runtime.store.claim_next()
    assert claimed is not None
    await runtime.store.mark_retry_or_fail(claimed.id, error=error, backoff_sec=0)


@pytest.mark.asyncio
async def test_cancel_failed_of_kind_only_matching_reason(runtime: TaskRuntime) -> None:
    await _fail(runtime, "tg_cleanup", "нет обработчика kind='tg_cleanup'")
    await _fail(runtime, "tg_cleanup", "timeout")
    await _fail(runtime, "tg_push", "нет обработчика kind='tg_push'")
    n = await runtime.cancel_failed_of_kind(
        "tg_cleanup", reason="нет обработчика kind='tg_cleanup'"
    )
    assert n == 1
    rows = await runtime.list_recent()
    by_error = {row.last_error: row.status for row in rows if row.kind == "tg_cleanup"}
    assert by_error["нет обработчика kind='tg_cleanup'"] == TaskStatus.CANCELLED
    assert by_error["timeout"] == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_retry_failed_of_kind_respects_reason(runtime: TaskRuntime) -> None:
    await _fail(runtime, "salary_estimate", "timeout")
    await _fail(runtime, "salary_estimate", "boom")
    n = await runtime.retry_failed_of_kind("salary_estimate", reason="timeout")
    assert n == 1
    rows = await runtime.list_recent()
    statuses = {row.last_error or "reset": row.status for row in rows}
    assert TaskStatus.PENDING in statuses.values()


@pytest.mark.asyncio
async def test_admin_cancel_failed_writes_audit(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _fail(runtime, "tg_cleanup", "нет обработчика kind='tg_cleanup'")
    actions: list[str] = []

    async def fake_log(action: str, *_args: object, **_kwargs: object) -> None:
        actions.append(action)

    monkeypatch.setattr(admin_svc, "_log_action", fake_log)
    n = await cancel_failed_of_kind(
        "tg_cleanup", actor_id=1, reason="нет обработчика kind='tg_cleanup'"
    )
    assert n == 1
    assert actions == ["task_cancel"]
