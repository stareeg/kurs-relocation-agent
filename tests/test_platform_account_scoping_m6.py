"""M6 (plans/multitenancy_gaps_2026_08_06.md §3.8-3.10): платформенный слой —
usage/очередь/логи/SSE — учится личности запроса. Без живой БД (см. tests/test_rls_platform.py
для кросс-аккаунтных RLS-проверок с маркером `db`).
"""

from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime

import pytest

from core.config import reset_current_account_id, set_current_account_id
from core.domains.opportunities.salary_async import _idem_key
from core.platform.observability.logging import record_to_dict
from core.platform.tasks.models import TaskRecord, TaskStatus
from core.platform.tasks.runtime import TaskRuntime
from core.platform.tasks.store import MemoryTaskStore


def test_insert_usage_sql_includes_account_id() -> None:
    """Контракт insert: account_id в VALUES (без живой БД, тот же приём, что L-02)."""
    from core.platform.repo import usage as usage_repo

    src = inspect.getsource(usage_repo.insert_usage)
    assert "account_id" in src


def test_load_usage_metrics_requires_account_id() -> None:
    """§9 п.3: без операторского исключения — account_id обязателен, не keyword с default."""
    from core.platform.repo.usage import load_usage_metrics

    sig = inspect.signature(load_usage_metrics)
    assert sig.parameters["account_id"].default is inspect.Parameter.empty


def test_record_to_dict_picks_up_current_account_id() -> None:
    token = set_current_account_id(42)
    try:
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
        row = record_to_dict(record)
        assert row["account_id"] == 42
        assert "account_id" not in (row.get("fields") or {})
    finally:
        reset_current_account_id(token)


def test_record_to_dict_account_id_none_outside_context() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    row = record_to_dict(record)
    assert row["account_id"] is None


def test_salary_estimate_idem_key_includes_account() -> None:
    """§3.10 риски: vacancy_id публичен — два аккаунта на одной вакансии не должны схлопнуться
    в одну фоновую задачу."""
    key_a = _idem_key("vac-1", account_id=1)
    key_b = _idem_key("vac-1", account_id=2)
    assert key_a != key_b
    assert "1" in key_a and "2" in key_b


@pytest.mark.asyncio
async def test_memory_store_list_recent_filters_to_own_and_system_tasks() -> None:
    store = MemoryTaskStore()
    await store.enqueue(
        kind="salary_estimate",
        payload={},
        priority=100,
        idempotency_key=None,
        run_at=datetime.now(UTC),
        max_attempts=3,
        account_id=1,
    )
    await store.enqueue(
        kind="salary_estimate",
        payload={},
        priority=100,
        idempotency_key=None,
        run_at=datetime.now(UTC),
        max_attempts=3,
        account_id=2,
    )
    await store.enqueue(
        kind="attachments_gc",
        payload={},
        priority=100,
        idempotency_key=None,
        run_at=datetime.now(UTC),
        max_attempts=3,
        account_id=None,
    )

    rows = await store.list_recent(account_id=1)
    kinds_and_accounts = {(r.kind, r.account_id) for r in rows}
    assert ("salary_estimate", 1) in kinds_and_accounts
    assert ("attachments_gc", None) in kinds_and_accounts
    assert ("salary_estimate", 2) not in kinds_and_accounts

    unfiltered = await store.list_recent()
    assert len(unfiltered) == 3


@pytest.mark.asyncio
async def test_worker_sets_account_context_around_account_task_only() -> None:
    """Воркер оборачивает хендлер account-задачи хуком (п.2), но не трогает системные."""
    runtime = TaskRuntime(store=MemoryTaskStore())
    seen: list[int | None] = []

    async def enter(account_id: int) -> str:
        seen.append(account_id)
        return f"token-{account_id}"

    async def exit_(token: str) -> None:
        seen.append(None)
        assert token.startswith("token-")

    runtime.set_account_context(enter, exit_)

    calls: list[str] = []

    async def handler(_payload: dict) -> None:
        calls.append("ran")

    runtime.register_handler("account_kind", handler)
    runtime.register_handler("system_kind", handler)

    account_task = TaskRecord(
        id=1,
        kind="account_kind",
        account_id=7,
        status=TaskStatus.PENDING,
        run_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    system_task = TaskRecord(
        id=2,
        kind="system_kind",
        account_id=None,
        status=TaskStatus.PENDING,
        run_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    await runtime._execute(account_task)  # noqa: SLF001 — тест воркера напрямую
    await runtime._execute(system_task)  # noqa: SLF001

    assert seen == [7, None]  # только account-задача дошла до enter/exit
    assert calls == ["ran", "ran"]
