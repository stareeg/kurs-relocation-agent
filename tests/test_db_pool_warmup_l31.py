"""L-31: min_size пула поднят и берётся из настроек (прогрев — побочный эффект create_pool)."""

from __future__ import annotations

from typing import Any

import asyncpg
import pytest

from core.config import clear_settings_cache, get_settings
from core.platform.db import pool as pool_module


@pytest.fixture(autouse=True)
def _clear_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


class _FakePool:
    """Достаточно для create_pool() — реального коннекта asyncpg не поднимаем в юнит-тесте."""


@pytest.fixture
def captured_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_create_pool(dsn: str, **kwargs: Any) -> _FakePool:
        captured["dsn"] = dsn
        captured.update(kwargs)
        return _FakePool()

    monkeypatch.setattr(asyncpg, "create_pool", _fake_create_pool)
    return captured


async def test_create_pool_defaults_min_size_from_settings(captured_kwargs: dict[str, Any]):
    settings = get_settings()
    await pool_module.create_pool()
    assert captured_kwargs["min_size"] == settings.postgres_pool_min_size
    assert captured_kwargs["max_size"] == settings.postgres_pool_max_size


async def test_default_min_size_is_warmed_above_one():
    """R-05 против регрессии: было min_size=1 — первый запрос после старта платил за коннект."""
    assert get_settings().postgres_pool_min_size >= 4


async def test_create_pool_explicit_args_override_settings(captured_kwargs: dict[str, Any]):
    await pool_module.create_pool(min_size=1, max_size=2)
    assert captured_kwargs["min_size"] == 1
    assert captured_kwargs["max_size"] == 2


async def test_pool_min_size_configurable_via_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POSTGRES_POOL_MIN_SIZE", "8")
    clear_settings_cache()
    assert get_settings().postgres_pool_min_size == 8
