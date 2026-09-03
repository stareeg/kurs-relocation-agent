"""A-20: очередь platform/tasks — приоритеты, идемпотентность, ретраи, переживание «рестарта»."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from core.platform.tasks import (
    CronSpec,
    MemoryTaskStore,
    TaskStatus,
    reset_runtime_for_tests,
)
from core.platform.tasks.runtime import TaskRuntime


@pytest.fixture
def runtime() -> TaskRuntime:
    return reset_runtime_for_tests(MemoryTaskStore())


async def test_enqueue_idempotent_by_key(runtime: TaskRuntime) -> None:
    a = await runtime.enqueue("demo", payload={"n": 1}, idempotency_key="k1", priority=10)
    b = await runtime.enqueue("demo", payload={"n": 2}, idempotency_key="k1", priority=10)
    assert a.id == b.id
    assert a.payload["n"] == 1
    rows = await runtime.list_recent()
    assert len(rows) == 1


async def test_priority_order(runtime: TaskRuntime) -> None:
    done: list[str] = []

    async def handler(payload: dict) -> None:
        done.append(str(payload["name"]))

    runtime.register_handler("demo", handler)
    await runtime.enqueue("demo", payload={"name": "low"}, priority=200)
    await runtime.enqueue("demo", payload={"name": "high"}, priority=10)

    await runtime.start()
    for _ in range(50):
        if len(done) >= 2:
            break
        await asyncio.sleep(0.05)
    await runtime.stop()

    assert done == ["high", "low"]


async def test_retry_then_fail(runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def handler(_payload: dict) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("core.platform.tasks.runtime._BACKOFF_BASE_SEC", 0.01)
    monkeypatch.setattr("core.platform.tasks.runtime._BACKOFF_CAP_SEC", 0.02)
    runtime.register_handler("flaky", handler)
    task = await runtime.enqueue("flaky", max_attempts=2, priority=1)
    await runtime.start()

    for _ in range(100):
        rows = await runtime.list_recent()
        row = next(r for r in rows if r.id == task.id)
        if row.status == TaskStatus.FAILED:
            break
        await asyncio.sleep(0.05)

    await runtime.stop()
    rows = await runtime.list_recent()
    row = next(r for r in rows if r.id == task.id)
    assert row.status == TaskStatus.FAILED
    assert calls == 2
    assert "boom" in row.last_error


async def test_reclaim_stuck_survives_restart(runtime: TaskRuntime) -> None:
    """Симуляция рестарта: running → reclaim → воркер доводит до done."""
    done = asyncio.Event()

    async def handler(_payload: dict) -> None:
        done.set()

    runtime.register_handler("warm", handler)
    task = await runtime.enqueue("warm", idempotency_key="warm:day", priority=1)

    # Имитация падения процесса mid-flight.
    claimed = await runtime.store.claim_next()
    assert claimed is not None and claimed.id == task.id
    assert claimed.status == TaskStatus.RUNNING

    n = await runtime.reclaim_stuck()
    assert n == 1
    assert await runtime.has_active("warm:day")

    await runtime.start()
    try:
        await asyncio.wait_for(done.wait(), timeout=3)
    finally:
        await runtime.stop()

    rows = await runtime.list_recent()
    row = next(r for r in rows if r.id == task.id)
    assert row.status == TaskStatus.DONE


async def test_cron_enqueues_once_per_day(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime.now().astimezone().replace(hour=9, minute=35, second=0, microsecond=0)

    monkeypatch.setattr(
        "core.platform.tasks.runtime._local_now",
        lambda: fixed,
    )

    runtime.add_cron(
        CronSpec(
            schedule_id="morning_digest",
            hour=9,
            minute=30,
            kind="morning_digest",
            misfire_grace_sec=3600,
        )
    )
    await runtime._tick_crons()  # noqa: SLF001
    await runtime._tick_crons()  # noqa: SLF001 — второй тик не дублирует

    rows = await runtime.list_recent()
    digest = [r for r in rows if r.kind == "morning_digest"]
    assert len(digest) == 1
    assert digest[0].idempotency_key == f"morning_digest:{fixed.date().isoformat()}"
