"""OQ-8 / U-1: режим подтверждения действий агента — маршрут настроек и хранение в account_settings."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.agent import runs as runs_router
from api.security import AccountContext, require_account_context
from core.platform.repo import settings as settings_repo

_ACCOUNT = AccountContext(account_id=7, telegram_user_id=70, telegram_username="u7", role="member")


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[int | None, str], Any]:
    """account_settings в памяти: (account_id, key) → value."""
    data: dict[tuple[int | None, str], Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: int | None, db: Any = None):
        return data.get((account_id, key), default)

    async def fake_set(key: str, value: Any, *, account_id: int | None, db: Any = None) -> None:
        data[(account_id, key)] = value

    monkeypatch.setattr(settings_repo, "get_setting", fake_get)
    monkeypatch.setattr(settings_repo, "set_setting", fake_set)
    return data


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(runs_router.router)
    app.dependency_overrides[require_account_context] = lambda: _ACCOUNT
    return TestClient(app)


def test_confirm_mode_defaults_to_ask_and_persists_per_account(stored: dict) -> None:
    with _client() as client:
        assert client.get("/api/agent/settings").json() == {"confirm_mode": "ask"}
        put = client.put("/api/agent/settings", json={"confirm_mode": "auto"})
        assert put.status_code == 200
        assert put.json() == {"confirm_mode": "auto"}
        assert client.get("/api/agent/settings").json() == {"confirm_mode": "auto"}
        assert client.put("/api/agent/settings", json={"confirm_mode": "yolo"}).status_code == 422
    assert stored == {(7, "agent_confirm_mode"): "auto"}


async def test_unknown_stored_mode_reads_as_ask(stored: dict) -> None:
    stored[(7, "agent_confirm_mode")] = "whatever"
    assert await settings_repo.get_agent_confirm_mode(account_id=7) == "ask"
    with pytest.raises(ValueError):
        await settings_repo.set_agent_confirm_mode("whatever", account_id=7)


def test_approval_edit_respects_tool_limits(stored: dict) -> None:
    """Правка короче 40 знаков отвергается на входе, до менеджера запусков."""
    with _client() as client:
        res = client.post(
            "/api/agent/runs/1/approval",
            json={"approved": True, "edits": {"cover_note": "коротко"}},
        )
        assert res.status_code == 422
