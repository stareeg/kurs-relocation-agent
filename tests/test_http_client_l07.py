"""L-07: общий keep-alive httpx-клиент к OpenRouter."""

from __future__ import annotations

import httpx
import pytest
from langchain_core.messages import HumanMessage

from core.platform import http as http_pkg
from core.platform.http import (
    close_http_client,
    get_http_client,
    init_http_client,
    make_client,
    request_timeout,
)
from core.platform.http import client as http_client_mod
from core.platform.llm.openrouter_chat import OpenRouterChatModel


@pytest.fixture(autouse=True)
async def _reset_http_singleton():
    await close_http_client()
    yield
    await close_http_client()


def test_request_timeout_splits_connect_and_read() -> None:
    t = request_timeout(42.0)
    assert t.connect == http_client_mod.CONNECT_TIMEOUT_S
    assert t.read == 42.0
    assert t.write == http_client_mod.WRITE_TIMEOUT_S
    assert t.pool == http_client_mod.POOL_TIMEOUT_S


@pytest.mark.asyncio
async def test_make_client_works_with_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    async with make_client(transport=httpx.MockTransport(handler)) as client:
        resp = await client.get("https://example.test/")
        assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_get_http_client_is_singleton() -> None:
    a = get_http_client()
    b = await init_http_client()
    assert a is b is get_http_client()
    await close_http_client()
    c = get_http_client()
    assert c is not a


@pytest.mark.asyncio
async def test_openrouter_reuses_shared_client_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Два LLM-вызова без _transport идут через один и тот же singleton."""
    seen_clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    shared = make_client(
        transport=httpx.MockTransport(handler),
        apply_settings_proxy=False,
    )
    http_client_mod._client = shared

    real_get = http_pkg.get_http_client

    def tracking_get() -> httpx.AsyncClient:
        client = real_get()
        seen_clients.append(client)
        return client

    monkeypatch.setattr(http_pkg, "get_http_client", tracking_get)

    llm = OpenRouterChatModel(
        primary_model="openai/gpt-5.6-luna",
        api_key="test-key",
        max_retries=1,
    )
    assert await llm.ainvoke([HumanMessage(content="a")])
    assert (await llm.ainvoke([HumanMessage(content="b")])).content == "ok"
    assert len(seen_clients) == 2
    assert seen_clients[0] is seen_clients[1] is shared


@pytest.mark.asyncio
async def test_openrouter_mock_transport_bypasses_singleton() -> None:
    """Регресс: llm._transport = MockTransport не трогает/не требует singleton."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "mock-ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1},
            },
        )

    llm = OpenRouterChatModel(
        primary_model="openai/gpt-5.6-luna",
        api_key="test-key",
        max_retries=1,
    )
    llm._transport = httpx.MockTransport(handler)
    result = await llm.ainvoke([HumanMessage(content="hi")])
    assert result.content == "mock-ok"
    assert http_client_mod._client is None
