"""Этап 6: проверка ключа OpenRouter до выдачи. Сырой ключ не течёт в ответы и логи."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routers.meta import admin as admin_router
from api.security import AccountContext, require_account_context
from core.platform.admin.models import AdminKeyBalance, AdminKeyBalances, AdminKeyVerify
from core.platform.openrouter_keys import (
    IssuedKeyBalance,
    KeyProbe,
    mask_key,
    sanitize_key,
    verify_key,
)

_RAW = "sk-or-v1-this-is-the-secret-key-value-abcdef"
_HINT = mask_key(_RAW)
_OWNER = AccountContext(account_id=1, telegram_user_id=10, telegram_username="op", role="owner")
_MEMBER = AccountContext(
    account_id=2, telegram_user_id=20, telegram_username="friend", role="member"
)


def _alive_payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "limit": 100,
        "limit_remaining": 74.5,
        "usage": 25.5,
        "is_free_tier": False,
        "name": "friend-lena",
        "label": "sk-or-v1-…cdef",
    }
    data.update(overrides)
    return {"data": data}


def _client_for(status: int, payload: dict[str, object] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).rstrip("/").endswith("/key")
        assert request.headers["Authorization"] == f"Bearer {_RAW}"
        return httpx.Response(status, json=payload if payload is not None else {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _dump_record(record: logging.LogRecord) -> str:
    return json.dumps(record.__dict__, default=str, ensure_ascii=False)


@pytest.fixture
def captured_logs() -> list[str]:
    """Только наши логгеры: httpx на DEBUG мог бы утащить Authorization в заголовок."""
    chunks: list[str] = []

    class Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            chunks.append(_dump_record(record))

    handler = Handler()
    handler.setLevel(logging.DEBUG)
    names = (
        "core.platform.openrouter_keys",
        "core.platform.admin",
        "core.platform.admin.service",
        "api.routers.meta.admin",
    )
    attached: list[logging.Logger] = []
    for name in names:
        log = logging.getLogger(name)
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        attached.append(log)
    yield chunks
    for log in attached:
        log.removeHandler(handler)


def _assert_no_secret(*blobs: object) -> None:
    for blob in blobs:
        text = blob if isinstance(blob, str) else json.dumps(blob, default=str)
        assert _RAW not in text
        # Перенос/пробел внутри ключа тоже не должен утечь кусками длиннее маски.
        assert "this-is-the-secret" not in text


@pytest.mark.asyncio
async def test_verify_alive_returns_limit_and_hides_key(
    monkeypatch: pytest.MonkeyPatch, captured_logs: list[str]
) -> None:
    monkeypatch.setattr(
        "core.platform.openrouter_keys.get_http_client",
        lambda: _client_for(200, _alive_payload()),
    )
    probe = await verify_key(f"  {_RAW}\n")
    assert probe.alive is True
    assert probe.network_error is False
    assert probe.limit == 100
    assert probe.limit_remaining == 74.5
    assert probe.usage == 25.5
    assert probe.is_free_tier is False
    assert probe.key_hint == _HINT
    dumped = asdict(probe)
    _assert_no_secret(dumped, *captured_logs)


@pytest.mark.asyncio
async def test_verify_dead_key(monkeypatch: pytest.MonkeyPatch, captured_logs: list[str]) -> None:
    monkeypatch.setattr(
        "core.platform.openrouter_keys.get_http_client",
        lambda: _client_for(401, {"error": {"message": "Invalid API key"}}),
    )
    probe = await verify_key(_RAW)
    assert probe.alive is False
    assert probe.network_error is False
    assert probe.error == "ключ не принят"
    assert probe.key_hint == _HINT
    _assert_no_secret(asdict(probe), *captured_logs)


@pytest.mark.asyncio
async def test_verify_network_error_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, captured_logs: list[str]
) -> None:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError("boom"))
    monkeypatch.setattr("core.platform.openrouter_keys.get_http_client", lambda: client)
    probe = await verify_key(_RAW)
    assert probe.alive is False
    assert probe.network_error is True
    assert probe.error == "OpenRouter не ответил"
    _assert_no_secret(asdict(probe), *captured_logs)


@pytest.mark.asyncio
async def test_verify_openrouter_5xx_is_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.platform.openrouter_keys.get_http_client",
        lambda: _client_for(503, {"error": "unavailable"}),
    )
    probe = await verify_key(_RAW)
    assert probe.alive is False
    assert probe.network_error is True


def test_sanitize_key_strips_whitespace_and_newlines() -> None:
    assert sanitize_key(f" \n{_RAW}\r\n ") == _RAW
    assert sanitize_key("") == ""


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router.router)
    return app


def test_verify_endpoint_403_for_member() -> None:
    app = _app()
    app.dependency_overrides[require_account_context] = lambda: _MEMBER
    with TestClient(app) as client:
        response = client.post("/api/admin/keys/verify", json={"key": _RAW})
        assert response.status_code == 403
        _assert_no_secret(response.text)


def test_verify_endpoint_hides_raw_key_in_response(
    monkeypatch: pytest.MonkeyPatch, captured_logs: list[str]
) -> None:
    app = _app()
    app.dependency_overrides[require_account_context] = lambda: _OWNER
    result = AdminKeyVerify(
        alive=True,
        key_hint=_HINT,
        limit=100,
        limit_remaining=74.5,
        usage=25.5,
        is_free_tier=False,
        label="friend-lena",
    )
    monkeypatch.setattr(admin_router, "verify_user_key", AsyncMock(return_value=result))
    with TestClient(app) as client:
        response = client.post("/api/admin/keys/verify", json={"key": _RAW})
    assert response.status_code == 200
    body = response.json()
    assert body["alive"] is True
    assert body["limit_remaining"] == 74.5
    assert "key" not in body
    _assert_no_secret(body, response.text, *captured_logs)


def test_verify_endpoint_network_error_is_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app()
    app.dependency_overrides[require_account_context] = lambda: _OWNER
    monkeypatch.setattr(
        admin_router,
        "verify_user_key",
        AsyncMock(
            return_value=AdminKeyVerify(
                alive=False, network_error=True, error="OpenRouter не ответил", key_hint=_HINT
            )
        ),
    )
    with TestClient(app) as client:
        response = client.post("/api/admin/keys/verify", json={"key": _RAW})
    assert response.status_code == 200
    assert response.json()["network_error"] is True
    _assert_no_secret(response.text)


def test_balances_endpoint_hides_raw_key(
    monkeypatch: pytest.MonkeyPatch, captured_logs: list[str]
) -> None:
    app = _app()
    app.dependency_overrides[require_account_context] = lambda: _OWNER
    monkeypatch.setattr(
        admin_router,
        "refresh_key_balances",
        AsyncMock(
            return_value=AdminKeyBalances(
                items=[
                    AdminKeyBalance(
                        account_id=7,
                        telegram_username="lena",
                        alive=True,
                        key_hint=_HINT,
                        limit_remaining=12.0,
                    )
                ]
            )
        ),
    )
    with TestClient(app) as client:
        response = client.post("/api/admin/keys/balances")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["account_id"] == 7
    assert body["items"][0]["limit_remaining"] == 12.0
    _assert_no_secret(body, response.text, *captured_logs)


@pytest.mark.asyncio
async def test_refresh_balances_skips_empty_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.platform import openrouter_keys as svc

    class _Pool:
        async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
            assert "origin = 'admin'" in sql
            return [{"account_id": 7, "telegram_username": "lena", "raw_key": None}]

    monkeypatch.setattr("core.platform.db.pool.get_pool", lambda: _Pool())
    called = False

    async def boom(_raw: str) -> KeyProbe:
        nonlocal called
        called = True
        raise AssertionError("пустой ключ не должен идти в OpenRouter")

    monkeypatch.setattr(svc, "verify_key", boom)
    rows = await svc.refresh_admin_issued_balances()
    assert called is False
    assert len(rows) == 1
    assert rows[0].account_id == 7
    assert rows[0].probe.alive is False
    assert rows[0].probe.error == "ключ не найден в настройках"


@pytest.mark.asyncio
async def test_refresh_balances_calls_verify_per_admin_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.platform import openrouter_keys as svc

    class _Pool:
        async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
            return [{"account_id": 7, "telegram_username": "lena", "raw_key": _RAW}]

    monkeypatch.setattr("core.platform.db.pool.get_pool", lambda: _Pool())
    monkeypatch.setattr(
        svc,
        "verify_key",
        AsyncMock(return_value=KeyProbe(alive=True, key_hint=_HINT, limit_remaining=3.0)),
    )
    rows = await svc.refresh_admin_issued_balances()
    assert rows == [
        IssuedKeyBalance(
            account_id=7,
            telegram_username="lena",
            probe=KeyProbe(alive=True, key_hint=_HINT, limit_remaining=3.0),
        )
    ]
    svc.verify_key.assert_awaited_once_with(_RAW)
