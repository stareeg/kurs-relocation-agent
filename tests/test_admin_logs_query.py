"""Этап 5.1: GET /api/admin/logs — фильтры, капы, курсор, 403 для member."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.meta import admin as admin_router
from api.security import AccountContext, require_account_context
from core.platform.admin import audit as admin_audit
from core.platform.admin.models import AdminError
from core.platform.admin.service import (
    DEFAULT_LOG_LEVELS,
    MAX_LOG_LIMIT,
    MIN_LOG_QUERY_LEN,
    compile_log_query,
    load_logs,
    parse_log_levels,
    resolve_log_window,
)

_MEMBER = AccountContext(
    account_id=2, telegram_user_id=20, telegram_username="friend", role="member"
)
_NOW = datetime(2026, 8, 25, 15, 0, tzinfo=UTC)


def test_default_window_is_one_hour() -> None:
    start, end = resolve_log_window(None, None, now=_NOW)
    assert end == _NOW
    assert end - start == timedelta(hours=1)


def test_window_longer_than_14_days_is_rejected() -> None:
    with pytest.raises(AdminError, match="14 дней"):
        resolve_log_window(_NOW - timedelta(days=15), _NOW)


def test_window_start_after_end_is_rejected() -> None:
    with pytest.raises(AdminError, match="раньше"):
        resolve_log_window(_NOW, _NOW - timedelta(minutes=1))


def test_naive_datetimes_get_utc() -> None:
    start, end = resolve_log_window(datetime(2026, 8, 25, 12, 0), datetime(2026, 8, 25, 13, 0))
    assert start.tzinfo is not None
    assert end.tzinfo is not None


def test_parse_log_levels_defaults_and_adds_critical() -> None:
    assert parse_log_levels("") == list(DEFAULT_LOG_LEVELS)
    assert parse_log_levels("мусор") == list(DEFAULT_LOG_LEVELS)
    levels = parse_log_levels("ERROR,WARNING")
    assert "ERROR" in levels and "WARNING" in levels and "CRITICAL" in levels
    assert parse_log_levels("INFO") == ["INFO"]


def test_compile_log_query_passes_filters_as_parameters() -> None:
    start, end = resolve_log_window(None, None, now=_NOW)
    sql, args = compile_log_query(
        since=start,
        until=end,
        levels=["ERROR", "CRITICAL"],
        account_id=7,
        logger_name="core.platform",
        event_name="АДМИН",
        query="timeout",
        limit=50,
    )
    assert "drop table" not in sql
    assert "timeout" not in sql
    assert "АДМИН" not in sql
    assert "core.platform" not in sql
    assert args[0] == start and args[1] == end
    assert args[2] == ["ERROR", "CRITICAL"]
    assert 7 in args
    assert "core.platform" in args
    assert "АДМИН" in args
    assert "timeout" in args
    assert args[-1] == 51
    assert "l.level = any($3::text[])" in sql
    assert "order by l.ts desc, l.id desc" in sql


def test_compile_log_query_filters_by_telegram_user_id() -> None:
    start, end = resolve_log_window(None, None, now=_NOW)
    sql, args = compile_log_query(
        since=start,
        until=end,
        levels=["ERROR"],
        telegram_user_id=42,
        limit=50,
    )
    assert 42 in args
    assert "a.telegram_user_id" in sql
    assert "42" not in sql


def test_compile_log_query_cursor_is_keyset_not_offset() -> None:
    start, end = resolve_log_window(None, None, now=_NOW)
    cursor_ts = _NOW - timedelta(minutes=10)
    sql, args = compile_log_query(
        since=start,
        until=end,
        levels=["ERROR"],
        cursor=(cursor_ts, 42),
        limit=100,
    )
    assert "offset" not in sql.lower()
    assert "(l.ts, l.id) <" in sql
    assert cursor_ts in args
    assert 42 in args


def test_compile_log_query_limit_is_capped_by_caller_plus_one() -> None:
    start, end = resolve_log_window(None, None, now=_NOW)
    _, args = compile_log_query(since=start, until=end, levels=["ERROR"], limit=MAX_LOG_LIMIT)
    assert args[-1] == MAX_LOG_LIMIT + 1


def test_decode_cursor_roundtrip() -> None:
    ts = datetime(2026, 8, 25, 14, 32, 1, tzinfo=UTC)
    raw = admin_audit.encode_cursor(ts, 99)
    decoded_ts, decoded_id = admin_audit.decode_cursor(raw)
    assert decoded_id == 99
    assert decoded_ts == ts


def test_decode_cursor_rejects_garbage() -> None:
    with pytest.raises(AdminError, match="курсор"):
        admin_audit.decode_cursor("not-a-cursor")
    with pytest.raises(AdminError, match="курсор"):
        admin_audit.decode_cursor("12:not-a-date")


@pytest.mark.asyncio
async def test_load_logs_rejects_short_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("core.platform.admin.service._fetch_logs", AsyncMock(return_value=[]))
    with pytest.raises(AdminError, match="трёх"):
        await load_logs(query="ab")
    assert MIN_LOG_QUERY_LEN == 3


@pytest.mark.asyncio
async def test_load_logs_caps_limit_and_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    ts = _NOW - timedelta(minutes=1)
    fetched = [
        {
            "id": 2,
            "ts": ts,
            "level": "ERROR",
            "logger": "api.main",
            "event": "HTTP",
            "task_id": "t-1",
            "msg": "boom",
            "account_id": 7,
            "telegram_username": "kate",
            "fields": {"path": "/score"},
        },
        {"id": 1, "ts": ts - timedelta(seconds=1), "level": "WARNING", "msg": "slow"},
    ]

    async def fake_fetch(sql: str, args: list[object]) -> list[dict[str, object]]:
        assert args[-1] == MAX_LOG_LIMIT + 1
        return fetched

    monkeypatch.setattr("core.platform.admin.service._fetch_logs", fake_fetch)
    page = await load_logs(limit=500, query="boom")
    assert page.items[0].account_id == 7
    assert page.items[0].telegram_username == "kate"
    assert page.items[0].fields == {"path": "/score"}
    assert page.items[0].task_id == "t-1"
    assert page.next_cursor is None
    assert page.since is not None and page.until is not None


@pytest.mark.asyncio
async def test_load_logs_next_cursor_from_last_row(monkeypatch: pytest.MonkeyPatch) -> None:
    ts = _NOW - timedelta(minutes=1)
    rows = [
        {"id": i, "ts": ts - timedelta(seconds=i), "level": "ERROR", "msg": f"e{i}"}
        for i in range(3)
    ]

    async def fake_fetch(sql: str, args: list[object]) -> list[dict[str, object]]:
        _ = sql
        limit_plus = int(args[-1])
        return rows[:limit_plus]

    monkeypatch.setattr("core.platform.admin.service._fetch_logs", fake_fetch)
    page = await load_logs(limit=2)
    assert len(page.items) == 2
    assert page.next_cursor == admin_audit.encode_cursor(rows[1]["ts"], 1)


def test_member_gets_403_on_logs_and_audit() -> None:
    app = FastAPI()
    app.include_router(admin_router.router)
    app.dependency_overrides[require_account_context] = lambda: _MEMBER
    with TestClient(app) as client:
        assert client.get("/api/admin/logs").status_code == 403
        assert client.get("/api/admin/audit").status_code == 403


def test_logs_query_sets_statement_timeout() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "core/platform/admin/service.py").read_text(
        encoding="utf-8"
    )
    assert "SET LOCAL statement_timeout" in src
    assert "LOG_STATEMENT_TIMEOUT" in src
