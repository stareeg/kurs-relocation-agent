"""L-17: кэш результатов LLM (память + ключ feature:prompt_version:input_hash)."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field

from core.platform.cache.result_cache import (
    MemoryResultCache,
    reset_result_cache_for_tests,
    set_result_cache_for_tests,
)
from core.platform.llm.call import CallContext, _cache_key, _prompt_version, run
from core.platform.llm.registry import LlmFeature, register, unregister_for_tests


class _Point(BaseModel):
    x: int = 0
    y: int = Field(default=0)


@pytest.fixture(autouse=True)
def _isolate_cache():
    set_result_cache_for_tests(MemoryResultCache())
    yield
    reset_result_cache_for_tests()


@pytest.mark.asyncio
async def test_memory_cache_roundtrip_and_ttl():
    cache = MemoryResultCache()
    await cache.set("a", "hello", ttl_s=60)
    assert await cache.get("a") == "hello"
    await cache.set("b", "gone", ttl_s=0.01)
    await asyncio.sleep(0.03)
    assert await cache.get("b") is None


@pytest.mark.asyncio
async def test_memory_cache_pydantic_roundtrip():
    cache = MemoryResultCache()
    await cache.set("p", _Point(x=3, y=4), ttl_s=60)
    got = await cache.get("p")
    assert isinstance(got, _Point)
    assert got.x == 3 and got.y == 4


def test_cache_key_includes_prompt_version_and_changes_with_input():
    feat = LlmFeature(
        name="_l17_key",
        tier="basic",
        prompt_in_code=True,
        max_tokens=1024,
        budget_ms=5_000,
    )
    assert _prompt_version(feat) == "in_code"
    k1 = _cache_key(
        feat,
        system_text="sys",
        user_text="u1",
        schema=None,
        temperature=0.3,
        max_tokens=1024,
        ctx=None,
    )
    k2 = _cache_key(
        feat,
        system_text="sys",
        user_text="u2",
        schema=None,
        temperature=0.3,
        max_tokens=1024,
        ctx=None,
    )
    assert k1.startswith("_l17_key:in_code:")
    assert k1 != k2
    k_explicit = _cache_key(
        feat,
        system_text="sys",
        user_text="u1",
        schema=None,
        temperature=0.3,
        max_tokens=1024,
        ctx=CallContext(cache_key="vac-42"),
    )
    assert k_explicit == "_l17_key:in_code:vac-42"


@pytest.mark.asyncio
async def test_run_second_call_hits_cache(monkeypatch):
    name = "_l17_run_hit"
    unregister_for_tests(name)
    feat = register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=5_000,
            retries=1,
        )
    )
    calls = {"n": 0}

    class _FakeChat:
        async def ainvoke(self, _messages, config=None):
            calls["n"] += 1

            class _Msg:
                content = "from-llm"

            return _Msg()

    monkeypatch.setattr(
        "core.platform.llm.call.chat_model_for",
        lambda *a, **k: _FakeChat(),
    )
    try:
        r1 = await run(feat, user="same-input", system="fixed")
        r2 = await run(feat, user="same-input", system="fixed")
        assert r1 == r2 == "from-llm"
        assert calls["n"] == 1
        # skip_cache — снова идём в модель
        r3 = await run(
            feat,
            user="same-input",
            system="fixed",
            ctx=CallContext(skip_cache=True, skip_single_flight=True),
        )
        assert r3 == "from-llm"
        assert calls["n"] == 2
    finally:
        unregister_for_tests(name)


@pytest.mark.asyncio
async def test_run_structured_cache_returns_model(monkeypatch):
    name = "_l17_struct_hit"
    unregister_for_tests(name)
    feat = register(
        LlmFeature(
            name=name,
            tier="basic",
            prompt_in_code=True,
            max_tokens=1024,
            budget_ms=5_000,
            retries=1,
        )
    )
    calls = {"n": 0}

    class _FakeStructured:
        async def ainvoke(self, _messages, config=None):
            calls["n"] += 1
            return _Point(x=9, y=1)

    class _FakeChat:
        def with_structured_output(self, schema, max_retries=1):
            assert schema is _Point
            return _FakeStructured()

    monkeypatch.setattr(
        "core.platform.llm.call.chat_model_for",
        lambda *a, **k: _FakeChat(),
    )
    try:
        a = await run(feat, user="p", schema=_Point)
        b = await run(feat, user="p", schema=_Point)
        assert isinstance(a, _Point) and isinstance(b, _Point)
        assert a.x == b.x == 9
        assert calls["n"] == 1
    finally:
        unregister_for_tests(name)
