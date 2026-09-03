"""A-07: единая точка вызова `run` + контракт «ainvoke только в platform/llm»."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from core.platform.cache.single_flight import SingleFlight
from core.platform.llm.call import CallContext, run
from core.platform.llm.registry import LlmFeature, register, unregister_for_tests

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def temp_feature():
    """Временная LlmFeature, снимаемая после теста: иначе она утекает в реестр и валит A-09."""
    created: list[str] = []

    def _make(**kwargs) -> LlmFeature:
        feature = register(LlmFeature(**kwargs))
        created.append(feature.name)
        return feature

    yield _make
    for name in created:
        unregister_for_tests(name)


_RE_STRUCTURED = re.compile(r"\bwith_structured_output\b")
_RE_AINVOKE = re.compile(r"\.ainvoke\s*\(")
_RE_ASTREAM = re.compile(r"\.astream\s*\(")


def _iter_python_sources(*packages: str) -> list[Path]:
    paths: list[Path] = []
    for package in packages:
        root = ROOT / package
        if not root.is_dir():
            continue
        paths.extend(p for p in root.rglob("*.py") if p.is_file())
    return paths


def test_ainvoke_and_structured_only_in_platform_llm():
    """Проверка A-07: домены не зовут with_structured_output / ainvoke / astream напрямую."""
    offenders: list[str] = []
    for path in _iter_python_sources("core", "bot_app", "api"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("core/platform/llm/"):
            continue
        src = path.read_text(encoding="utf-8")
        hits: list[str] = []
        if _RE_STRUCTURED.search(src):
            hits.append("with_structured_output")
        if _RE_AINVOKE.search(src):
            hits.append("ainvoke")
        if _RE_ASTREAM.search(src):
            hits.append("astream")
        if hits:
            offenders.append(f"{rel}: {', '.join(hits)}")
    assert not offenders, (
        "Прямые LLM-вызовы вне core/platform/llm. Используй run():\n"
        + "\n".join(offenders)
    )


def test_chat_model_for_not_imported_outside_platform_llm():
    offenders: list[str] = []
    for path in _iter_python_sources("core", "bot_app", "api"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("core/platform/llm/"):
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(
            r"from\s+core\.platform\.llm(?:\.registry)?\s+import\s+[^\n]*\bchat_model_for\b",
            src,
        ):
            offenders.append(rel)
    assert not offenders, (
        "chat_model_for вне platform/llm — зови run():\n" + "\n".join(offenders)
    )


@pytest.mark.asyncio
async def test_single_flight_collapses_parallel_calls():
    flight = SingleFlight()
    calls = 0

    async def factory() -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return "ok"

    results = await asyncio.gather(
        flight.do("k", factory),
        flight.do("k", factory),
        flight.do("k", factory),
        flight.do("k", factory),
        flight.do("k", factory),
    )
    assert results == ["ok"] * 5
    assert calls == 1


class _Point(BaseModel):
    x: int = 0
    y: int = 0


@pytest.mark.asyncio
async def test_run_structured_with_injected_model(temp_feature):
    """run(schema=…) с инъекцией model не ходит в сеть."""

    class _FakeStructured:
        async def ainvoke(self, _messages, config=None):
            return _Point(x=1, y=2)

    class _FakeChat:
        def with_structured_output(self, schema, max_retries=1):
            assert schema is _Point
            assert max_retries == 1
            return _FakeStructured()

    feat = temp_feature(
        name="_test_a07_point",
        tier="basic",
        temperature=0.0,
        max_tokens=1024,
        budget_ms=5_000,
        retries=1,
        prompt_in_code=True,
    )
    result = await run(feat, user="point", schema=_Point, model=_FakeChat())  # type: ignore[arg-type]
    assert isinstance(result, _Point)
    assert result.x == 1 and result.y == 2


@pytest.mark.asyncio
async def test_run_stream_with_injected_model(temp_feature):
    class _Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class _FakeChat:
        async def astream(self, _messages, config=None):
            for piece in ("при", "вет"):
                yield _Chunk(piece)

    feat = temp_feature(
        name="_test_a07_stream",
        tier="basic",
        max_tokens=1024,
        budget_ms=5_000,
        prompt_in_code=True,
    )
    stream = await run(feat, user="hi", stream=True, model=_FakeChat())  # type: ignore[arg-type]
    parts = [p async for p in stream]
    assert "".join(parts) == "привет"


@pytest.mark.asyncio
async def test_run_respects_explicit_cache_key_skip(temp_feature):
    class _FakeChat:
        async def ainvoke(self, _messages, config=None):
            class _Msg:
                content = "ok"

            return _Msg()

    feat = temp_feature(
        name="_test_a07_ctx",
        tier="basic",
        max_tokens=1024,
        budget_ms=5_000,
        prompt_in_code=True,
    )
    text = await run(
        feat,
        user="x",
        model=_FakeChat(),  # type: ignore[arg-type]
        ctx=CallContext(cache_key="unit", skip_cache=True, skip_single_flight=True),
    )
    assert text == "ok"


@pytest.mark.asyncio
async def test_stall_warning_fires_past_half_budget(temp_feature, caplog):
    """§13 (local_context_blind_spots): различить зависший запрос от честно долгого ответа —
    WARNING на полпути budget_ms, до того как budget_ms вообще истечёт."""

    class _SlowChat:
        async def ainvoke(self, _messages, config=None):
            await asyncio.sleep(0.15)

            class _Msg:
                content = "ok"

            return _Msg()

    feat = temp_feature(
        name="_test_a07_stall_slow",
        tier="basic",
        max_tokens=1024,
        budget_ms=200,
        prompt_in_code=True,
    )
    caplog.set_level(logging.WARNING, logger="core.platform.llm.call")
    text = await run(feat, user="x", model=_SlowChat())  # type: ignore[arg-type]
    assert text == "ok"
    assert any("затянувшийся запрос" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_stall_warning_cancelled_after_fast_call(temp_feature, caplog):
    """Успешный быстрый вызов не должен оставлять фоновый таймер — иначе он всё равно
    отстрелит WARNING чуть позже, ложно обвиняя быстрый ответ в зависании."""

    class _FastChat:
        async def ainvoke(self, _messages, config=None):
            class _Msg:
                content = "ok"

            return _Msg()

    feat = temp_feature(
        name="_test_a07_stall_fast",
        tier="basic",
        max_tokens=1024,
        budget_ms=100,
        prompt_in_code=True,
    )
    caplog.set_level(logging.WARNING, logger="core.platform.llm.call")
    text = await run(feat, user="x", model=_FastChat())  # type: ignore[arg-type]
    assert text == "ok"
    await asyncio.sleep(0.08)  # дать таймеру шанс сработать, если он не был отменён
    assert not any("затянувшийся запрос" in r.message for r in caplog.records)
