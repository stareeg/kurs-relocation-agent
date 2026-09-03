"""Этап 8: полный разрез расхода и мягкий лимит на аккаунт.

8.1 — в строке разреза те же cache/latency/retries, что лежат в llm_usage.
8.2 — порог в app_settings, превышение = подсветка + очередь внимания.
8.3 (жёсткая отсечка) в этот этап не входит.
"""

from __future__ import annotations

from typing import Any

import pytest

import core.platform.admin.service as admin_svc
from core.platform.admin.service import (
    load_attention,
    load_people,
    load_spend,
    parse_spend_alert_usd,
    set_spend_alert,
)


def test_parse_spend_alert_usd_zero_means_off() -> None:
    assert parse_spend_alert_usd(None) == 0.0
    assert parse_spend_alert_usd(0) == 0.0
    assert parse_spend_alert_usd(-3) == 0.0
    assert parse_spend_alert_usd("нет") == 0.0
    assert parse_spend_alert_usd(True) == 0.0


def test_parse_spend_alert_usd_rounds_and_caps() -> None:
    assert parse_spend_alert_usd(12.345) == 12.35
    assert parse_spend_alert_usd("4.5") == 4.5
    assert parse_spend_alert_usd(50_000) == 10_000.0


class _Pool:
    def __init__(self, rows: dict[str, Any]) -> None:
        self.rows = rows
        self.queries: list[tuple[str, tuple[Any, ...]]] = []

    def _resolve(self, sql: str, args: tuple[Any, ...]) -> Any:
        self.queries.append((sql, args))
        for marker, value in self.rows.items():
            if marker in sql:
                return value
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        value = self._resolve(sql, args)
        return list(value or [])

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        value = self._resolve(sql, args)
        return dict(value) if isinstance(value, dict) else None

    def args_for(self, marker: str) -> tuple[Any, ...]:
        for sql, args in self.queries:
            if marker in sql:
                return args
        raise AssertionError(f"нет запроса с {marker!r}")


def _install(monkeypatch: pytest.MonkeyPatch, rows: dict[str, Any] | None = None) -> _Pool:
    pool = _Pool(rows or {})
    monkeypatch.setattr(admin_svc, "get_pool", lambda: pool)
    return pool


@pytest.mark.asyncio
async def test_spend_row_maps_cache_latency_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "from llm_usage u": [
                {
                    "key": "openai/gpt-5.6-luna",
                    "cost_usd": 1.2,
                    "tokens_in": 100,
                    "tokens_out": 40,
                    "calls": 10,
                    "cache_hits": 4,
                    "median_ms": 320.4,
                    "p95_ms": 910,
                    "retries": 2,
                }
            ]
        },
    )
    spend = await load_spend(days=14, group_by="model")
    row = spend.rows[0]
    assert row.cache_hits == 4
    assert row.cache_hit_rate == pytest.approx(0.4)
    assert row.median_ms == pytest.approx(320.4)
    assert row.p95_ms == pytest.approx(910)
    assert row.retries == 2
    assert row.retry_share == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_spend_row_rates_none_when_no_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "generate_series": [
                {
                    "key": "2026-08-01",
                    "cost_usd": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "calls": 0,
                    "cache_hits": 0,
                    "median_ms": None,
                    "p95_ms": None,
                    "retries": 0,
                }
            ]
        },
    )
    spend = await load_spend(days=14, group_by="day")
    row = spend.rows[0]
    assert row.cache_hit_rate is None
    assert row.retry_share is None
    assert row.median_ms is None


@pytest.mark.asyncio
async def test_spend_totals_include_latency_and_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "as today_usd": {
                "today_usd": 1.0,
                "month_usd": 2.0,
                "cache_hits": 3,
                "cache_calls": 10,
                "median_ms": 200,
                "p95_ms": 800,
                "retries": 1,
            }
        },
    )
    spend = await load_spend(days=14, group_by="model")
    assert spend.median_ms == pytest.approx(200)
    assert spend.p95_ms == pytest.approx(800)
    assert spend.retries == 1
    assert spend.retry_share == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_attention_skips_spend_query_when_alert_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _install(monkeypatch, {"as spend_alert_usd": {"spend_alert_usd": 0}})
    attention = await load_attention()
    assert attention.spend_alert_usd == 0
    assert attention.spend_over == []
    assert not any("having coalesce" in sql for sql, _ in pool.queries)


@pytest.mark.asyncio
async def test_attention_spend_over_matches_threshold_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KPI-принцип: карточки внимания = список превысивших порог."""
    over = [
        {"account_id": 4, "telegram_username": "lena", "month_usd": 12.4},
        {"account_id": 9, "telegram_username": "kate", "month_usd": 10.01},
    ]
    pool = _install(
        monkeypatch,
        {
            "as spend_alert_usd": {"spend_alert_usd": 10},
            "having coalesce": over,
        },
    )
    attention = await load_attention()
    assert attention.spend_alert_usd == pytest.approx(10)
    assert [item.account_id for item in attention.spend_over] == [4, 9]
    assert attention.spend_over[0].month_usd == pytest.approx(12.4)
    assert pool.args_for("having coalesce") == (10.0,)


@pytest.mark.asyncio
async def test_people_spend_alert_flag_uses_calendar_month(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "account_id": 4,
            "telegram_username": "lena",
            "telegram_user_id": 40,
            "role": "member",
            "status": "active",
            "month_cost_usd": 3.0,
            "spend_month_usd": 12.4,
            "total_count": 2,
        },
        {
            "account_id": 5,
            "telegram_username": "misha",
            "telegram_user_id": 50,
            "role": "member",
            "status": "active",
            "month_cost_usd": 20.0,
            "spend_month_usd": 4.0,
            "total_count": 2,
        },
    ]
    _install(
        monkeypatch,
        {
            "as spend_alert_usd": {"spend_alert_usd": 10},
            "total_count": rows,
        },
    )
    page = await load_people()
    by_id = {user.account_id: user for user in page.items}
    # Скользящие 30 дней у Миши больше — но порог смотрит календарный месяц.
    assert by_id[4].spend_alert is True
    assert by_id[5].spend_alert is False
    assert by_id[4].spend_month_usd == pytest.approx(12.4)


@pytest.mark.asyncio
async def test_set_spend_alert_writes_setting_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: dict[str, Any] = {}

    async def fake_set(key: str, value: Any, *, account_id: int | None, db: Any = None) -> None:
        _ = db
        written["key"] = key
        written["value"] = value
        written["account_id"] = account_id

    logged: dict[str, Any] = {}

    async def fake_log(action: str, actor_id: int, **fields: Any) -> None:
        logged["action"] = action
        logged["actor_id"] = actor_id
        logged.update(fields)

    monkeypatch.setattr(admin_svc, "set_setting", fake_set)
    monkeypatch.setattr(admin_svc, "_log_action", fake_log)
    result = await set_spend_alert(12.345, actor_id=1)
    assert result == pytest.approx(12.35)
    assert written == {
        "key": "admin_spend_alert_usd",
        "value": 12.35,
        "account_id": None,
    }
    assert logged["action"] == "spend_alert"
    assert logged["usd"] == pytest.approx(12.35)
    assert logged["actor_id"] == 1


@pytest.mark.asyncio
async def test_spend_day_attaches_model_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {
            "generate_series": [
                {
                    "key": "2026-08-25",
                    "cost_usd": 1.5,
                    "tokens_in": 10,
                    "tokens_out": 4,
                    "calls": 3,
                    "cache_hits": 1,
                    "median_ms": 100,
                    "p95_ms": 200,
                    "retries": 0,
                }
            ],
            "u.model": [
                {
                    "day": "2026-08-25",
                    "model": "openai/gpt-5.6-luna",
                    "cost_usd": 1.0,
                    "calls": 2,
                },
                {
                    "day": "2026-08-25",
                    "model": "google/gemini-3.7-flash",
                    "cost_usd": 0.5,
                    "calls": 1,
                },
            ],
        },
    )
    spend = await load_spend(days=14, group_by="day")
    assert spend.rows[0].segments[0].key == "openai/gpt-5.6-luna"
    assert spend.rows[0].segments[0].cost_usd == pytest.approx(1.0)
    assert spend.rows[0].segments[1].key == "google/gemini-3.7-flash"
