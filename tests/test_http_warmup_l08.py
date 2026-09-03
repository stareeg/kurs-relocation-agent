"""L-08: прогрев соединения OpenRouter (GET /models) на старте."""

from __future__ import annotations

import httpx
import pytest

from core.config import set_runtime_openrouter_key
from core.platform.http import close_http_client, make_client, warmup_openrouter
from core.platform.http import client as http_client_mod


@pytest.fixture(autouse=True)
async def _reset_http_singleton():
    await close_http_client()
    set_runtime_openrouter_key(None)
    yield
    await close_http_client()
    set_runtime_openrouter_key(None)


@pytest.mark.asyncio
async def test_warmup_get_models_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    shared = make_client(
        transport=httpx.MockTransport(handler),
        apply_settings_proxy=False,
    )
    http_client_mod._client = shared
    monkeypatch.setattr(
        http_client_mod,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_api_key": "sk-test",
                "openrouter_proxy": None,
                "llm_timeout_s": 90.0,
            },
        )(),
    )
    set_runtime_openrouter_key("sk-from-db")

    assert await warmup_openrouter() is True
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert str(seen[0].url).endswith("/models")
    assert seen[0].headers.get("Authorization") == "Bearer sk-from-db"


@pytest.mark.asyncio
async def test_warmup_network_error_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    shared = make_client(
        transport=httpx.MockTransport(handler),
        apply_settings_proxy=False,
    )
    http_client_mod._client = shared
    monkeypatch.setattr(
        http_client_mod,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_api_key": "sk-test",
                "openrouter_proxy": None,
                "llm_timeout_s": 90.0,
            },
        )(),
    )

    assert await warmup_openrouter() is False


@pytest.mark.asyncio
async def test_warmup_5xx_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "busy"})

    shared = make_client(
        transport=httpx.MockTransport(handler),
        apply_settings_proxy=False,
    )
    http_client_mod._client = shared
    monkeypatch.setattr(
        http_client_mod,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_api_key": "",
                "openrouter_proxy": None,
                "llm_timeout_s": 90.0,
            },
        )(),
    )

    assert await warmup_openrouter() is False
