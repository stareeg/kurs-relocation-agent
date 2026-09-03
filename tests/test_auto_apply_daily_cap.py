"""Дневной лимит автооткликов (2.7) — считаем через application_stages, без новой таблицы."""

from __future__ import annotations

from typing import Any

from core.domains.pipeline.auto_apply.config import auto_apply_daily_hard_cap
from core.domains.pipeline.auto_apply.daily_cap import auto_apply_source, count_today


def test_hard_caps_per_platform() -> None:
    assert auto_apply_daily_hard_cap("hh") == 150
    assert auto_apply_daily_hard_cap("getmatch") == 30
    assert auto_apply_daily_hard_cap("habr") == 30


class _FakePool:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.calls: list[tuple[Any, ...]] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append((sql, *args))
        return self.row


def test_auto_apply_source_naming() -> None:
    assert auto_apply_source("hh") == "auto_apply_hh"
    assert auto_apply_source("getmatch") == "auto_apply_getmatch"
    assert auto_apply_source("habr") == "auto_apply_habr"


async def test_count_today_parses_row() -> None:
    pool = _FakePool({"n": 3})
    result = await count_today("hh", account_id=7, db=pool)
    assert result == 3
    sql, account_id, source, stage = pool.calls[0]
    assert account_id == 7
    assert source == "auto_apply_hh"
    assert stage == "Отклик"
    assert "changed_at::date = current_date" in sql


async def test_count_today_no_row_is_zero() -> None:
    pool = _FakePool(None)
    result = await count_today("getmatch", account_id=1, db=pool)
    assert result == 0
