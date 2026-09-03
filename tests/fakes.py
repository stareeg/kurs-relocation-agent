"""Тестовые двойники портов.

Обычный модуль, а не `conftest`: импортируется явно там, где нужен, и не влияет на прогон
остальных тестов (`tests/conftest.py` по договорённости держит только UTF-8).

Домены после A-10 зовут LLM через `core.kernel.ports.llm()`, поэтому подмена — это фейковый
порт (параметром `llm=` или через `ports.use_ports(llm=…)`), а не monkeypatch платформенной
функции внутри модуля домена.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from core.kernel import ports
from core.kernel.vacancy import RawVacancy


class FakeVacancySource:
    """Двойник `VacancySource`: отдаёт заготовленные `RawVacancy` без сети."""

    name = "fake"

    def __init__(
        self,
        vacancies: Sequence[RawVacancy] | None = None,
        *,
        name: str = "fake",
    ) -> None:
        self.name = name
        self._vacancies = list(vacancies or [])

    async def fetch(self, query: str) -> list[RawVacancy]:
        _ = query
        return list(self._vacancies)

    def parse(self, html: str) -> RawVacancy:
        if self._vacancies:
            return self._vacancies[0]
        return RawVacancy(text=html, source=self.name)


class FakeChannel:
    """Двойник `Channel`: только идентичность, без логики."""

    def __init__(self, name: str, *, source_tag: str | None = None) -> None:
        self.name = name
        self.source_tag = source_tag or f"{name}_test"


class FakeLlm:
    """Порт-заглушка: пишет вызовы в `calls`, отдаёт заготовленные ответы.

    `text` / `texts` — ответы `complete` (по очереди, последний повторяется);
    `result` / `results` — ответы `structured`;
    `error` — исключение вместо ответа;
    `on_complete` / `on_structured` — колбэк для нетривиальных случаев (получает feature и kwargs).
    """

    def __init__(
        self,
        *,
        text: str = "",
        texts: Sequence[str] | None = None,
        result: Any = None,
        results: Sequence[Any] | None = None,
        error: Exception | None = None,
        on_complete: Callable[..., Any] | None = None,
        on_structured: Callable[..., Any] | None = None,
    ) -> None:
        self._texts = list(texts) if texts is not None else ([text] if text else [""])
        self._results = list(results) if results is not None else [result]
        self._error = error
        self._on_complete = on_complete
        self._on_structured = on_structured
        self.calls: list[dict[str, Any]] = []

    @property
    def features(self) -> list[str]:
        return [c["feature"] for c in self.calls]

    def _next(self, pool: list[Any]) -> Any:
        return pool.pop(0) if len(pool) > 1 else (pool[0] if pool else None)

    async def complete(self, feature: str, **kwargs: Any) -> str:
        self.calls.append({"feature": feature, **kwargs})
        if self._error:
            raise self._error
        if self._on_complete:
            value = self._on_complete(feature, **kwargs)
            return await value if hasattr(value, "__await__") else value
        return self._next(self._texts)

    async def structured(self, feature: str, *, schema: type, **kwargs: Any) -> Any:
        self.calls.append({"feature": feature, "schema": schema, **kwargs})
        if self._error:
            raise self._error
        if self._on_structured:
            value = self._on_structured(feature, schema=schema, **kwargs)
            return await value if hasattr(value, "__await__") else value
        return self._next(self._results)

    def stream(self, feature: str, **kwargs: Any):
        self.calls.append({"feature": feature, "stream": True, **kwargs})
        chunks = list(self._texts)

        async def _gen():
            if self._error:
                raise self._error
            for chunk in chunks:
                yield chunk

        return _gen()


class RaisingLlm(FakeLlm):
    """Порт, который не должен быть вызван вообще."""

    def __init__(self, message: str = "LLM не должна вызываться") -> None:
        super().__init__()
        self._message = message

    async def complete(self, feature: str, **kwargs: Any) -> str:
        raise AssertionError(f"{self._message} (feature={feature})")

    async def structured(self, feature: str, *, schema: type, **kwargs: Any) -> Any:
        raise AssertionError(f"{self._message} (feature={feature})")


def use_fake_llm(monkeypatch, llm: FakeLlm) -> FakeLlm:
    """Связать фейковый LLM-порт на время теста (снимается финализатором monkeypatch).

    Вариант без `with` — для тестов, где вызов домена идёт несколькими шагами.
    Подменяем снимок портов целиком через monkeypatch: он же вернёт прежний на teardown.
    """
    previous = ports.current()
    monkeypatch.setattr(
        ports,
        "_current",
        ports.Ports(
            llm=llm,
            cache=previous.cache,
            clock=previous.clock,
            events=previous.events,
            notifier=previous.notifier,
            vacancy_sources=dict(previous.vacancy_sources),
            channels=dict(previous.channels),
        ),
    )
    return llm


__all__ = ["FakeChannel", "FakeLlm", "FakeVacancySource", "RaisingLlm", "use_fake_llm"]
