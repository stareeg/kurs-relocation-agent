"""Процесс не забирает задачи, для которых у него нет handler."""

from __future__ import annotations

import asyncio

import pytest

from core.platform.tasks import MemoryTaskStore, TaskStatus, reset_runtime_for_tests
from core.platform.tasks.runtime import TaskRuntime


@pytest.fixture
def runtime() -> TaskRuntime:
    return reset_runtime_for_tests(MemoryTaskStore())


async def test_claim_next_skips_kinds_without_handler(runtime: TaskRuntime) -> None:
    done: list[str] = []

    async def handle_known(_payload: dict) -> None:
        done.append("known")

    runtime.register_handler("known", handle_known)
    await runtime.enqueue("unknown", priority=1)
    await runtime.enqueue("known", priority=10)

    claimed_known = await runtime.store.claim_next(kinds=("known",))
    assert claimed_known is not None and claimed_known.kind == "known"

    leftover = await runtime.store.claim_next(kinds=("known",))
    assert leftover is None
    unknown = await runtime.store.claim_next()
    assert unknown is not None and unknown.kind == "unknown"


async def test_empty_handler_set_claims_nothing(runtime: TaskRuntime) -> None:
    await runtime.enqueue("tg_cleanup")
    assert await runtime.store.claim_next(kinds=()) is None
    row = await runtime.store.claim_next()
    assert row is not None and row.kind == "tg_cleanup"


async def test_worker_does_not_fail_foreign_kind(runtime: TaskRuntime) -> None:
    done: list[str] = []

    async def handle_known(_payload: dict) -> None:
        done.append("ok")

    runtime.register_handler("known", handle_known)
    foreign = await runtime.enqueue("tg_cleanup", max_attempts=1, priority=1)
    await runtime.enqueue("known", priority=10)
    await runtime.start()
    for _ in range(40):
        if done:
            break
        await asyncio.sleep(0.05)
    await runtime.stop()

    assert done == ["ok"]
    rows = {row.id: row for row in await runtime.list_recent()}
    assert rows[foreign.id].status == TaskStatus.PENDING
    assert rows[foreign.id].last_error == ""
