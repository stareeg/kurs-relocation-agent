"""A-10: порты `core/kernel/ports.py` и композиционный корень `core/app/wiring.py`.

Дефолты (clock/cache/events/notifier) работают без связывания; LLM без связывания падает
громко; реализации из `platform` удовлетворяют протоколам.
"""

from __future__ import annotations

import asyncio

import pytest

from core.kernel import ports
from core.kernel.errors import LlmError, PortNotBoundError


@pytest.fixture(autouse=True)
def _clean_ports():
    """Каждый тест начинает с несвязанных портов и не протекает в соседние."""
    ports.reset()
    yield
    ports.reset()


async def test_defaults_work_without_wiring():
    assert isinstance(ports.clock(), ports.Clock)
    assert isinstance(ports.cache(), ports.CachePort)
    assert isinstance(ports.events(), ports.EventBus)
    assert isinstance(ports.notifier(), ports.Notifier)

    now = ports.clock().now()
    assert now.tzinfo is not None  # UTC-aware: без tz даты доменов расходятся с БД

    cache = ports.cache()
    await cache.set("k", 42)
    assert await cache.get("k") == 42
    await cache.delete("k")
    assert await cache.get("k") is None


async def test_memory_cache_respects_ttl():
    cache = ports.MemoryCache()
    await cache.set("k", "v", ttl_s=0.01)
    assert await cache.get("k") == "v"
    await asyncio.sleep(0.02)
    assert await cache.get("k") is None


def test_in_process_bus_isolates_failing_subscriber():
    class Ping:
        pass

    seen: list[str] = []
    bus = ports.InProcessEventBus()
    bus.subscribe(Ping, lambda _e: (_ for _ in ()).throw(RuntimeError("подписчик упал")))
    bus.subscribe(Ping, lambda _e: seen.append("ok"))

    bus.publish(Ping())  # падение первого не должно ронять издателя
    assert seen == ["ok"]


def test_unbound_llm_raises_instead_of_silent_fallback(monkeypatch: pytest.MonkeyPatch):
    # Отключаем ленивое автосвязывание, чтобы проверить именно «порт не связан».
    monkeypatch.setattr(ports, "_autowire", lambda: None)
    with pytest.raises(PortNotBoundError):
        ports.llm()


def test_unknown_vacancy_source_raises():
    with pytest.raises(PortNotBoundError):
        ports.vacancy_source("hh")


def test_unknown_channel_raises():
    with pytest.raises(PortNotBoundError):
        ports.channel("web")


# --------------------------------------------------------------------------- связывание


class _FakeLlm:
    async def complete(self, feature, **kwargs):
        return f"complete:{feature}"

    async def structured(self, feature, *, schema, **kwargs):
        return schema()

    def stream(self, feature, **kwargs):
        async def _gen():
            yield feature

        return _gen()


def test_bind_and_use_ports_override():
    fake = _FakeLlm()
    ports.bind(llm=fake)
    assert ports.llm() is fake

    other = _FakeLlm()
    with ports.use_ports(llm=other):
        assert ports.llm() is other
    assert ports.llm() is fake  # контекст вернул прежний порт


def test_bind_without_overwrite_keeps_existing():
    fake = _FakeLlm()
    ports.bind(llm=fake)
    ports.bind(llm=_FakeLlm(), overwrite=False)
    assert ports.llm() is fake


def test_vacancy_source_registry():
    from core.kernel.vacancy import RawVacancy

    class _Source:
        name = "hh"

        async def fetch(self, query: str):
            return [RawVacancy(vacancy_id=query, text="x" * 50, source="hh")]

        def parse(self, html: str) -> RawVacancy:
            return RawVacancy(text=html, source="hh")

    source = _Source()
    ports.register_vacancy_source(source)
    assert ports.vacancy_source("hh") is source
    assert isinstance(source, ports.VacancySource)


# --------------------------------------------------------------------------- реализации


def test_platform_implementations_satisfy_protocols():
    from core.app.wiring import PlatformCache, PlatformLlm

    assert isinstance(PlatformLlm(), ports.LlmPort)
    assert isinstance(PlatformCache(), ports.CachePort)


def test_wire_default_ports_is_idempotent_and_keeps_fakes():
    from core.app.wiring import PlatformLlm, wire_default_ports

    wire_default_ports()
    first = ports.llm()
    assert isinstance(first, PlatformLlm)

    wire_default_ports()
    assert ports.llm() is first  # повторный вызов не подменяет реализацию

    fake = _FakeLlm()
    ports.bind(llm=fake)
    wire_default_ports()
    assert ports.llm() is fake  # тестовый порт переживает повторное связывание

    wire_default_ports(force=True)
    assert isinstance(ports.llm(), PlatformLlm)


async def test_platform_llm_translates_provider_error_to_llm_error(monkeypatch: pytest.MonkeyPatch):
    """Домен ловит `LlmError`, а не `OpenRouterError` — иначе except тянет импорт platform."""
    from core.app import wiring
    from core.platform.llm import OpenRouterError

    async def boom(*args, **kwargs):
        raise OpenRouterError("502 upstream")

    monkeypatch.setattr(wiring, "run", boom)
    with pytest.raises(LlmError):
        await wiring.PlatformLlm().complete("weak_bullets", user="x")


async def test_platform_llm_translates_rate_limit_to_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
):
    """A-15: HTTP 429 провайдера → RateLimited (api отдаст 429), не общий LlmError/503."""
    from core.app import wiring
    from core.kernel.errors import RateLimited
    from core.platform.llm import OpenRouterRateLimitError

    async def boom(*args, **kwargs):
        raise OpenRouterRateLimitError("HTTP 429")

    monkeypatch.setattr(wiring, "run", boom)
    with pytest.raises(RateLimited):
        await wiring.PlatformLlm().complete("weak_bullets", user="x")


async def test_platform_llm_translates_budget_timeout(monkeypatch: pytest.MonkeyPatch):
    from core.app import wiring

    async def boom(*args, **kwargs):
        raise TimeoutError("budget_ms")

    monkeypatch.setattr(wiring, "run", boom)
    with pytest.raises(LlmError):
        await wiring.PlatformLlm().complete("weak_bullets", user="x")
