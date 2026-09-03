"""L-25: снапшоты «Рынка» по расписанию — чистые функции стейлнесса/бакета + self-reschedule."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.domains.market import snapshot_dirty
from core.domains.market.snapshot_refresh import (
    MARKET_SNAPSHOT_INTERVAL_SEC,
    MARKET_SNAPSHOT_KIND,
    _bucket_key,
    is_market_snapshot_stale,
    is_situation_stale,
)
from core.platform.tasks import MemoryTaskStore, TaskStatus, reset_runtime_for_tests
from core.platform.tasks.runtime import TaskRuntime


@pytest.fixture(autouse=True)
def _reset_snapshot_dirty():
    """L-26: дирти-трекер — модульный глобал, тесты этого файла считают «всё грязное» как до L-26."""
    snapshot_dirty.reset()
    yield
    snapshot_dirty.reset()


def test_stale_none_is_stale() -> None:
    assert is_market_snapshot_stale(None) is True
    assert is_situation_stale(None) is True


def test_stale_fresh_snapshot_not_stale() -> None:
    now = datetime.now(UTC)
    assert is_market_snapshot_stale(now) is False
    assert is_situation_stale(now) is False


def test_stale_old_snapshot_is_stale() -> None:
    old = datetime.now(UTC) - timedelta(hours=2)
    assert is_market_snapshot_stale(old) is True  # порог — 3 цикла по 5 мин
    assert is_situation_stale(old) is False  # порог — 36ч


def test_stale_naive_datetime_treated_as_utc() -> None:
    naive_now = datetime.now(UTC).replace(tzinfo=None)
    assert is_market_snapshot_stale(naive_now) is False


def test_bucket_key_stable_within_window_changes_across() -> None:
    base = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)
    k1 = _bucket_key("k", at=base, interval_sec=300)
    k2 = _bucket_key("k", at=base + timedelta(seconds=299), interval_sec=300)
    k3 = _bucket_key("k", at=base + timedelta(seconds=301), interval_sec=300)
    assert k1 == k2
    assert k1 != k3


@pytest.fixture
def runtime() -> TaskRuntime:
    return reset_runtime_for_tests(MemoryTaskStore())


async def test_refresh_market_snapshots_reschedules_itself(
    runtime: TaskRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Обработчик после прогона кладёт свой следующий запуск в ту же очередь (self-reschedule)."""
    from core.domains.market import snapshot_refresh as mod

    async def _fake_pulse(**_kw):
        from core.domains.market.pulse import MarketPulse

        return MarketPulse(available=False)

    async def _fake_grid(**_kw):
        from core.domains.market.market_grid import MarketGrid

        return MarketGrid(available=False)

    async def _fake_search(**_kw):
        from core.domains.market.search_metrics import SearchMetrics

        return SearchMetrics(available=False)

    async def _fake_save_snapshot(*_a, **_kw):
        return None

    async def _fake_record_daily(*_a, **_kw):
        return None

    monkeypatch.setattr("core.domains.market.pulse.get_market_pulse", _fake_pulse)
    monkeypatch.setattr("core.domains.market.market_grid.get_market_grid", _fake_grid)
    monkeypatch.setattr(
        "core.domains.market.search_metrics.get_search_metrics", _fake_search
    )
    monkeypatch.setattr(
        "core.domains.market.analytics_cache.save_snapshot", _fake_save_snapshot
    )
    monkeypatch.setattr(
        "core.domains.market.market_snapshot.record_daily_pulse_state", _fake_record_daily
    )

    await mod._refresh_market_snapshots({})

    rows = await runtime.list_recent()
    assert len(rows) == 1
    assert rows[0].kind == MARKET_SNAPSHOT_KIND
    assert rows[0].status == TaskStatus.PENDING
    delta = (rows[0].run_at - datetime.now(UTC)).total_seconds()
    assert MARKET_SNAPSHOT_INTERVAL_SEC - 5 <= delta <= MARKET_SNAPSHOT_INTERVAL_SEC + 5


async def test_register_market_schedules_skips_kickoff_if_already_pending(
    runtime: TaskRuntime,
) -> None:
    """Рестарт процесса не заводит второй параллельный вечный цикл пересчёта (dev `--reload`)."""
    from core.domains.market.snapshot_refresh import register_market_schedules

    await runtime.enqueue(
        MARKET_SNAPSHOT_KIND,
        payload={},
        priority=150,
        idempotency_key="already-scheduled",
        run_at=datetime.now(UTC) + timedelta(seconds=60),
        max_attempts=3,
    )

    await register_market_schedules()

    rows = await runtime.list_recent()
    assert len([r for r in rows if r.kind == MARKET_SNAPSHOT_KIND]) == 1
