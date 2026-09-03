"""L-02: колонки таймингов в llm_usage + запись из call.run."""

from __future__ import annotations

from pathlib import Path

from core.platform.llm.usage import (
    NoopUsageSink,
    UsageFact,
    begin_usage_capture,
    emit_usage,
    end_usage_capture,
    flush_usage_capture,
    set_default_usage_sink,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATION = ROOT / "core" / "platform" / "db" / "migrations" / "0075_llm_usage_timings.sql"


class _CapturingSink(NoopUsageSink):
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(
        self,
        agent: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        *,
        tier: str = "basic",
        ttfb_ms: int | None = None,
        total_ms: int | None = None,
        queue_ms: int | None = None,
        attempt: int | None = None,
        cache_hit: bool = False,
    ) -> None:
        self.rows.append(
            {
                "agent": agent,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost": cost,
                "tier": tier,
                "ttfb_ms": ttfb_ms,
                "total_ms": total_ms,
                "queue_ms": queue_ms,
                "attempt": attempt,
                "cache_hit": cache_hit,
            }
        )


def test_migration_0075_defines_timing_columns() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    for col in ("ttfb_ms", "total_ms", "queue_ms", "attempt", "cache_hit"):
        assert col in sql, col


def test_emit_usage_without_capture_writes_sink_immediately() -> None:
    sink = _CapturingSink()
    set_default_usage_sink(sink)
    try:
        emit_usage(
            "job_search",
            "test/model",
            10,
            20,
            0.001,
            ttfb_ms=100,
            total_ms=120,
            queue_ms=5,
            attempt=1,
        )
        assert len(sink.rows) == 1
        row = sink.rows[0]
        assert row["ttfb_ms"] == 100
        assert row["total_ms"] == 120
        assert row["queue_ms"] == 5
        assert row["attempt"] == 1
        assert row["cache_hit"] is False
    finally:
        set_default_usage_sink(None)


def test_capture_defers_until_flush_from_call_run() -> None:
    sink = _CapturingSink()
    set_default_usage_sink(sink)
    try:
        facts, token = begin_usage_capture()
        try:
            emit_usage(
                "chat",
                "test/model",
                1,
                2,
                0.01,
                ttfb_ms=50,
                total_ms=80,
                queue_ms=0,
                attempt=2,
            )
            assert sink.rows == []
            assert len(facts) == 1
            flush_usage_capture(facts, queue_ms=15)
        finally:
            end_usage_capture(token)
        assert len(sink.rows) == 1
        row = sink.rows[0]
        assert row["agent"] == "chat"
        assert row["ttfb_ms"] == 50
        assert row["total_ms"] == 80
        assert row["queue_ms"] == 15  # A-07 override на первом факте
        assert row["attempt"] == 2
    finally:
        set_default_usage_sink(None)


def test_flush_overrides_timings_from_a07() -> None:
    sink = _CapturingSink()
    set_default_usage_sink(sink)
    try:
        facts = [
            UsageFact(
                agent="prep",
                model="m",
                tokens_in=1,
                tokens_out=1,
                cost=0.0,
                ttfb_ms=1,
                total_ms=2,
                queue_ms=0,
                attempt=1,
            )
        ]
        flush_usage_capture(facts, ttfb_ms=200, total_ms=350, queue_ms=10)
        row = sink.rows[0]
        assert row["ttfb_ms"] == 200
        assert row["total_ms"] == 350
        assert row["queue_ms"] == 10
    finally:
        set_default_usage_sink(None)


def test_insert_usage_sql_includes_timing_columns() -> None:
    """Контракт insert: новые колонки в VALUES (без живой БД)."""
    import inspect

    from core.platform.repo import usage as usage_repo

    src = inspect.getsource(usage_repo.insert_usage)
    assert "ttfb_ms" in src
    assert "cache_hit" in src
    assert "attempt" in src
