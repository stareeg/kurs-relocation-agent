"""Этап 1 редизайна админки: попадание в кэш не пишет нулевую латентность.

Раньше `call.run` на cache hit писал `ttfb_ms=0, total_ms=0, queue_ms=0`. Нули втекали в
`percentile_cont(...) filter (where total_ms is not null)` в разрезе расхода и роняли медиану
до «0 мс» в дни с высокой долей кэша (24 августа на проде — 69% попаданий). Экран показывал
мгновенный ответ провайдера, которого не было: LLM-вызова просто не случилось.

Тайминги там теперь `None` — строка остаётся (она нужна для доли кэша), но из расчёта
латентности выпадает по тому же фильтру.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

import core.platform.llm.call as call_mod
from core.platform.llm.registry import LlmFeature
from core.platform.llm.usage import NoopUsageSink, set_default_usage_sink


class _Answer(BaseModel):
    text: str = ""


class _CapturingSink(NoopUsageSink):
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def record(
        self,
        agent: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        *,
        tier: str = "basic",
        ttfb_ms: int | None = None,
        total_ms: int | None = None,
        queue_ms: int | None = None,
        attempt: int | None = None,
        cache_hit: bool = False,
    ) -> None:
        self.rows.append(
            {
                "agent": agent,
                "ttfb_ms": ttfb_ms,
                "total_ms": total_ms,
                "queue_ms": queue_ms,
                "attempt": attempt,
                "cache_hit": cache_hit,
            }
        )


class _HitCache:
    """Кэш, который всегда отвечает попаданием — до похода в провайдера дело не доходит."""

    def __init__(self, value: Any) -> None:
        self.value = value

    async def get(self, _key: str) -> Any:
        return self.value

    async def set(self, _key: str, _value: Any, **_kwargs: Any) -> None:  # pragma: no cover
        return None


@pytest.mark.asyncio
async def test_cache_hit_records_null_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    feature = LlmFeature(
        name="test_cache_hit",
        tier="basic",
        prompt_in_code=True,
        max_tokens=1024,
        budget_ms=8000,
    )
    monkeypatch.setattr(call_mod, "require_feature", lambda _name: feature)
    monkeypatch.setattr(call_mod, "get_result_cache", lambda: _HitCache(_Answer(text="из кэша")))

    sink = _CapturingSink()
    set_default_usage_sink(sink)
    try:
        result = await call_mod.run(
            feature,
            system="s",
            user="u",
            schema=_Answer,
        )
    finally:
        set_default_usage_sink(None)

    assert isinstance(result, _Answer)
    assert result.text == "из кэша"
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row["cache_hit"] is True
    assert row["ttfb_ms"] is None
    assert row["total_ms"] is None
    assert row["queue_ms"] is None
