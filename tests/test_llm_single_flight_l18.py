"""L-18: 5 параллельных одинаковых run() → один вызов модели."""

from __future__ import annotations

import asyncio

import pytest

from core.platform.cache.result_cache import (
    MemoryResultCache,
    reset_result_cache_for_tests,
    set_result_cache_for_tests,
)
from core.platform.cache.single_flight import (
    SingleFlight,
    reset_single_flight_for_tests,
    set_single_flight_for_tests,
)
from core.platform.llm.call import CallContext, run
from core.platform.llm.registry import LlmFeature, register, unregister_for_tests


@pytest.fixture(autouse=True)
def _isolate_flight_and_cache():
    set_result_cache_for_tests(MemoryResultCache())
    set_single_flight_for_tests(SingleFlight())
    yield
    reset_result_cache_for_tests()
    reset_single_flight_for_tests()


@pytest.mark.asyncio
async def test_five_parallel_run_share_one_model_call(monkeypatch):
    name = "_l18_parallel_run"
    unregister_for_tests(name)
    feat = register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=10_000,
            retries=1,
        )
    )
    calls = {"n": 0}
    started = asyncio.Event()
    release = asyncio.Event()

    class _FakeChat:
        async def ainvoke(self, _messages, config=None):
            calls["n"] += 1
            started.set()
            await release.wait()

            class _Msg:
                content = "shared"

            return _Msg()

    monkeypatch.setattr(
        "core.platform.llm.call.chat_model_for",
        lambda *a, **k: _FakeChat(),
    )
    try:
        tasks = [
            asyncio.create_task(run(feat, user="same", system="fixed"))
            for _ in range(5)
        ]
        await started.wait()
        # Все пятёрка уже в полёте, модель ещё держим — должен быть ровно один вызов.
        await asyncio.sleep(0.02)
        assert calls["n"] == 1
        release.set()
        results = await asyncio.gather(*tasks)
        assert results == ["shared"] * 5
        assert calls["n"] == 1
    finally:
        release.set()
        unregister_for_tests(name)


@pytest.mark.asyncio
async def test_single_flight_propagates_error_to_all_waiters(monkeypatch):
    name = "_l18_error_fanout"
    unregister_for_tests(name)
    feat = register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=10_000,
            retries=1,
        )
    )
    calls = {"n": 0}

    class _FakeChat:
        async def ainvoke(self, _messages, config=None):
            calls["n"] += 1
            await asyncio.sleep(0.03)
            raise RuntimeError("boom-llm")

    monkeypatch.setattr(
        "core.platform.llm.call.chat_model_for",
        lambda *a, **k: _FakeChat(),
    )
    try:
        results = await asyncio.gather(
            run(feat, user="x", system="s"),
            run(feat, user="x", system="s"),
            run(feat, user="x", system="s"),
            return_exceptions=True,
        )
        assert calls["n"] == 1
        assert all(isinstance(r, RuntimeError) for r in results)
    finally:
        unregister_for_tests(name)


@pytest.mark.asyncio
async def test_skip_single_flight_runs_separately(monkeypatch):
    name = "_l18_skip"
    unregister_for_tests(name)
    feat = register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=10_000,
            retries=1,
        )
    )
    calls = {"n": 0}
    gate = asyncio.Semaphore(0)

    class _FakeChat:
        async def ainvoke(self, _messages, config=None):
            calls["n"] += 1
            await gate.acquire()

            class _Msg:
                content = "solo"

            return _Msg()

    monkeypatch.setattr(
        "core.platform.llm.call.chat_model_for",
        lambda *a, **k: _FakeChat(),
    )
    try:
        t1 = asyncio.create_task(
            run(
                feat,
                user="x",
                system="s",
                ctx=CallContext(skip_single_flight=True, skip_cache=True),
            )
        )
        t2 = asyncio.create_task(
            run(
                feat,
                user="x",
                system="s",
                ctx=CallContext(skip_single_flight=True, skip_cache=True),
            )
        )
        await asyncio.sleep(0.05)
        assert calls["n"] == 2
        gate.release()
        gate.release()
        assert await t1 == "solo"
        assert await t2 == "solo"
    finally:
        unregister_for_tests(name)
