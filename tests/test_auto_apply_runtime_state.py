"""Рантайм-факты автооткликов (Фаза 8.2): площадка сегодня упёрлась в СВОЙ дневной лимит."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from core.domains.pipeline.auto_apply import runtime_state as rs


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: Any = None, db: Any = None) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        store[key] = value

    monkeypatch.setattr(rs, "get_setting", fake_get)
    monkeypatch.setattr(rs, "set_setting", fake_set)
    return store


async def test_not_limited_by_default(settings_store: dict[str, Any]) -> None:
    assert await rs.is_platform_limited_today("hh", account_id=1) is False


async def test_mark_then_is_limited_today(settings_store: dict[str, Any]) -> None:
    await rs.mark_platform_limit("hh", account_id=1)
    assert await rs.is_platform_limited_today("hh", account_id=1) is True
    # Соседнюю площадку не трогает.
    assert await rs.is_platform_limited_today("getmatch", account_id=1) is False


async def test_stale_mark_from_yesterday_does_not_count(settings_store: dict[str, Any]) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    settings_store[rs.KEY_RUNTIME_STATE] = {"hh": {"platform_limit_date": yesterday}}
    assert await rs.is_platform_limited_today("hh", account_id=1) is False


async def test_garbage_state_is_not_limited(settings_store: dict[str, Any]) -> None:
    settings_store[rs.KEY_RUNTIME_STATE] = "not-a-dict"
    assert await rs.is_platform_limited_today("hh", account_id=1) is False
