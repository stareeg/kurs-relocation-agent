"""L-09: разумные HTTP-ретраи (429/5xx/сеть да, 4xx нет; лимит — budget_ms)."""

from __future__ import annotations

import random

import httpx
import pytest
from langchain_core.messages import HumanMessage

from core.platform.http.retry import (
    backoff_with_jitter,
    can_retry_within_budget,
    is_retryable_http_status,
    plan_retry,
)
from core.platform.llm.openrouter_chat import OpenRouterChatModel, OpenRouterError


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        },
    )


def _llm(**overrides: object) -> OpenRouterChatModel:
    kwargs = {
        "primary_model": "openai/gpt-5.6-luna",
        "fallback_model": "",
        "tier_fallback_model": "",
        "api_key": "test-key",
        "max_retries": 3,
        "budget_ms": 30_000,
    }
    kwargs.update(overrides)
    llm = OpenRouterChatModel(**kwargs)
    llm._retry_rng = random.Random(0)  # детерминированный jitter
    return llm


def test_is_retryable_http_status() -> None:
    assert is_retryable_http_status(429) is True
    assert is_retryable_http_status(500) is True
    assert is_retryable_http_status(503) is True
    assert is_retryable_http_status(400) is False
    assert is_retryable_http_status(401) is False
    assert is_retryable_http_status(422) is False


def test_backoff_with_jitter_stays_in_range() -> None:
    rng = random.Random(1)
    for attempt in range(5):
        wait = backoff_with_jitter(attempt, base_s=1.0, cap_s=8.0, rng=rng)
        assert 0.0 <= wait <= 8.0


def test_can_retry_within_budget() -> None:
    assert can_retry_within_budget(100, 10_000, 0.5, reserve_ms=1_000) is True
    assert can_retry_within_budget(9_500, 10_000, 0.5, reserve_ms=1_000) is False
    assert can_retry_within_budget(0, None, 60.0) is True


def test_plan_retry_rejects_400() -> None:
    plan = plan_retry(
        status=400,
        attempt=0,
        elapsed_ms=10,
        budget_ms=30_000,
        safety_max=3,
        rng=random.Random(0),
    )
    assert plan.retry is False
    assert "not_retryable" in plan.reason


def test_plan_retry_429_within_budget() -> None:
    plan = plan_retry(
        status=429,
        attempt=0,
        elapsed_ms=10,
        budget_ms=30_000,
        safety_max=3,
        rng=random.Random(0),
    )
    assert plan.retry is True
    assert plan.reason == "429"
    assert plan.wait_s >= 0


def test_plan_retry_budget_exhausted() -> None:
    plan = plan_retry(
        status=429,
        attempt=0,
        elapsed_ms=50,
        budget_ms=500,  # меньше reserve_ms=1000
        safety_max=5,
        rng=random.Random(0),
    )
    assert plan.retry is False
    assert plan.reason == "budget_exhausted"


@pytest.mark.asyncio
async def test_429_one_retry_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": {"message": "rate"}})
        return _ok_response()

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    llm = _llm()
    llm._transport = httpx.MockTransport(handler)
    result = await llm.ainvoke([HumanMessage(content="hi")])
    assert result.content == "ok"
    assert len(calls) == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_400_no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "Schema is too complex."}})

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    llm = _llm()
    llm._transport = httpx.MockTransport(handler)
    with pytest.raises(OpenRouterError):
        await llm.ainvoke([HumanMessage(content="hi")])
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_503_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": "busy"})
        return _ok_response()

    async def fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    llm = _llm()
    llm._transport = httpx.MockTransport(handler)
    result = await llm.ainvoke([HumanMessage(content="hi")])
    assert result.content == "ok"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_429_no_retry_when_budget_too_small(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "rate"}})

    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    llm = _llm(budget_ms=500, max_retries=5)
    llm._transport = httpx.MockTransport(handler)
    with pytest.raises(OpenRouterError):
        await llm.ainvoke([HumanMessage(content="hi")])
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.asyncio
async def test_chat_model_for_passes_budget_ms() -> None:
    from core.platform.llm.registry import LlmFeature, chat_model_for, register, unregister_for_tests

    name = "_l09_budget_probe"
    unregister_for_tests(name)
    register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=120_000,
        )
    )
    try:
        model = chat_model_for(
            name,
            settings=type(
                "S",
                (),
                {
                    "tier_model": lambda self, t: "openai/gpt-5.6-luna",
                    "tier_fallback": lambda self, t: "",
                    "tier_effort": lambda self, t: None,
                    "openrouter_model_fallback": "",
                    "llm_timeout_s": 90.0,
                    "llm_max_retries": 3,
                    "openrouter_base_url": "https://openrouter.ai/api/v1",
                    "openrouter_api_key": "k",
                    "openrouter_proxy": None,
                    "agent_tier_overrides": {},
                },
            )(),
        )
        assert model.budget_ms == 120_000
        # L-13: HTTP-таймаут не короче budget (90с base → поднимаем до budget+5с).
        assert model.request_timeout == pytest.approx(120.0 + 5.0)
    finally:
        unregister_for_tests(name)
