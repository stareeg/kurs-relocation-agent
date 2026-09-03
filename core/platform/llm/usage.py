"""Cost-учёт LLM-вызовов (задача 0.2, подшаг 3; PG-версия — задача 1.1, подшаг 5).

UsageSink — интерфейс записи факта вызова (agent, model, tokens, cost). Раньше был временный
JSONL-фоллбэк в `data/usage/<день>.jsonl` (задача 0.2); теперь — только Postgres
(`PostgresUsageSink` из `core.platform.repo.usage`). Папка `data/` упразднена.

Если Postgres недоступен (lifespan API не поднял пул / не выставил sink через
`set_default_usage_sink`) — `default_usage_sink()` возвращает `NoopUsageSink`: cost не пишется,
LLM-вызов не падает.

Дневных cost-лимитов (soft/hard circuit breaker) здесь больше нет: они мешали бесшовной работе
(упирался в непонятный стоп), лимит трат настраивается на стороне OpenRouter. `today_cost_usd`
остаётся — его читает витрина /api/metrics и команда /cost в боте (только показ, не блокировка).
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from core.config import CoreSettings, get_settings, normalize_openrouter_model

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UsageRecord:
    ts: str
    agent: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float


@dataclass(slots=True)
class UsageFact:
    """Факт HTTP-вызова к модели; копится под `call.run`, пишется в sink оттуда."""

    agent: str
    model: str
    tokens_in: int
    tokens_out: int
    cost: float
    tier: str = "basic"
    ttfb_ms: int | None = None
    total_ms: int | None = None
    queue_ms: int | None = None
    attempt: int | None = None


@runtime_checkable
class UsageSink(Protocol):
    """Куда писать факт LLM-вызова. Реализация — Postgres (через lifespan API)."""

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
    ) -> None: ...

    def today_cost_usd(self) -> float: ...


class NoopUsageSink:
    """No-op sink: когда Postgres недоступен, cost не пишется, но LLM-вызов не падает.

    `today_cost_usd()` вернёт 0.0 (нет данных). Заменяет прежний JSONL-фолбэк в `data/usage/`
    (упразднён вместе с папкой `data/`).
    """

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
        return

    def today_cost_usd(self) -> float:
        return 0.0


_default_sink_override: UsageSink | None = None

# L-02: под `call.run` факты копятся здесь и flush'атся в sink из A-07.
_usage_capture: ContextVar[list[UsageFact] | None] = ContextVar("usage_capture", default=None)


def begin_usage_capture() -> tuple[list[UsageFact], Token[list[UsageFact] | None]]:
    """Начать захват фактов usage для текущего `call.run`."""
    facts: list[UsageFact] = []
    return facts, _usage_capture.set(facts)


def end_usage_capture(token: Token[list[UsageFact] | None]) -> None:
    """Откатить contextvar на предыдущее значение — чистая гигиена, не бизнес-логика.

    На стриминговых ответах (`call._stream_with_usage_flush`) `finally`, где живёт этот вызов,
    иногда резюмируется в другом `contextvars.Context`, чем тот, где сработал `begin_usage_
    capture` (ASGI/Starlette `StreamingResponse` может переиспользовать задачи между чанками) —
    тогда `reset()` кидает `ValueError: ... was created in a different Context`. Раньше это
    исключение улетало из `finally` и выглядело как обрыв генератора: клиент успевал получить
    весь ответ (`stream_answer` уже отдал все token-события), но само исключение попадало в
    внешний `except Exception` ДО кода персиста — обмен никогда не сохранялся в БД (баг
    «диалог пропадает», подтверждён живым тестом чата на «Рынке» — `market_chat_messages`
    оставался пустым при полностью отрисованном в UI ответе). Факты usage к этому моменту уже
    сброшены в sink (`flush_usage_capture` вызывается раньше в том же `finally`) — реальные
    данные не теряются, просто контекст, который мы не можем откатить, скоро исчезнет вместе
    со своей задачей.
    """
    try:
        _usage_capture.reset(token)
    except ValueError as exc:
        logger.debug("usage_capture: reset пропущен (другой Context, стрим уже завершён): %s", exc)


def emit_usage(
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
    """Записать usage: в capture (под call.run) или сразу в default sink (legacy-путь)."""
    capture = _usage_capture.get()
    if capture is not None:
        capture.append(
            UsageFact(
                agent=agent,
                model=model,
                tokens_in=int(tokens_in),
                tokens_out=int(tokens_out),
                cost=float(cost),
                tier=tier,
                ttfb_ms=ttfb_ms,
                total_ms=total_ms,
                queue_ms=queue_ms,
                attempt=attempt,
            )
        )
        return
    default_usage_sink().record(
        agent,
        model,
        tokens_in,
        tokens_out,
        cost,
        tier=tier,
        ttfb_ms=ttfb_ms,
        total_ms=total_ms,
        queue_ms=queue_ms,
        attempt=attempt,
        cache_hit=cache_hit,
    )


def flush_usage_capture(
    facts: list[UsageFact],
    *,
    queue_ms: int | None = None,
    ttfb_ms: int | None = None,
    total_ms: int | None = None,
    cache_hit: bool = False,
) -> None:
    """Сбросить захваченные факты в sink; тайминги A-07 перекрывают HTTP, если заданы."""
    sink = default_usage_sink()
    for index, fact in enumerate(facts):
        sink.record(
            fact.agent,
            fact.model,
            fact.tokens_in,
            fact.tokens_out,
            fact.cost,
            tier=fact.tier,
            ttfb_ms=ttfb_ms if ttfb_ms is not None else fact.ttfb_ms,
            total_ms=total_ms if total_ms is not None else fact.total_ms,
            queue_ms=(queue_ms if index == 0 and queue_ms is not None else fact.queue_ms),
            attempt=fact.attempt,
            cache_hit=cache_hit,
        )


def set_default_usage_sink(sink: UsageSink | None) -> None:
    """Подменить дефолтный UsageSink (None — вернуть NoopUsageSink). Вызывается в lifespan API:
    поднят пул PG → ставится `PostgresUsageSink`; падение пула → None → Noop."""
    global _default_sink_override
    _default_sink_override = sink


def default_usage_sink() -> UsageSink:
    """Дефолтный sink: Postgres (через override из lifespan) или Noop, если override не задан.

    Раньше фолбэком был JsonlUsageSink в `data/usage/`; теперь — Noop (папка `data/` упразднена).
    """
    return _default_sink_override or NoopUsageSink()


def _price_for(model: str, settings: CoreSettings) -> dict[str, float] | None:
    prices = settings.model_prices or {}
    model = normalize_openrouter_model(model)
    if model in prices:
        return prices[model]
    # матч по префиксу семейства (например "google/gemini", "openai/gpt-5.6-luna-20260709")
    for key, val in prices.items():
        if model.startswith(normalize_openrouter_model(key)):
            return val
    return None


async def today_llm_budget() -> dict:
    """LLM-затраты за сегодня: вызовы, USD, всего USD, разбивка по агентам.

    Мягкая деградация: нет PG/таблицы → нули (дайджест и /cost не падают).
    """
    out: dict = {"count": 0, "cost_usd": 0.0, "total_usd": 0.0, "by_agent": []}
    try:
        from core.platform.db.pool import get_pool

        pool = get_pool()
        row = await pool.fetchrow(
            "select count(*)::bigint c, coalesce(sum(cost_usd),0)::float8 cost "
            "from llm_usage where day = current_date"
        )
        out["count"] = int(row["c"])
        out["cost_usd"] = round(float(row["cost"]), 6)
        out["total_usd"] = round(
            float(await pool.fetchval("select coalesce(sum(cost_usd),0)::float8 from llm_usage")),
            6,
        )
        agents = await pool.fetch(
            "select agent, count(*)::bigint c, coalesce(sum(cost_usd),0)::float8 cost "
            "from llm_usage where day = current_date group by agent order by cost desc"
        )
        out["by_agent"] = [
            {"agent": a["agent"], "count": int(a["c"]), "cost_usd": round(float(a["cost"]), 6)}
            for a in agents
        ]
    except Exception as exc:  # noqa: BLE001 — нет PG/таблицы → нули
        logger.debug("today_llm_budget недоступен (нет PG?): %s", exc)
    return out


def compute_cost(
    model: str,
    tokens_in: int,
    tokens_out: int,
    settings: CoreSettings | None = None,
    *,
    provider_cost: float | None = None,
) -> float:
    """Стоимость вызова в USD. Приоритет: реальный cost от OpenRouter (usage.cost) → прайс из
    конфига → default-ставки. Реальный cost точнее (учитывает кэш-скидки и дрейф цен в .env),
    поэтому идёт первым — урок инцидента 2026-06-17 (docs/problems.md)."""
    if provider_cost is not None:
        return round(float(provider_cost), 6)
    settings = settings or get_settings()
    price = _price_for(model, settings)
    if price is not None:
        cin = float(price.get("input", settings.default_price_input_per_1m))
        cout = float(price.get("output", settings.default_price_output_per_1m))
    else:
        cin = settings.default_price_input_per_1m
        cout = settings.default_price_output_per_1m
    return round(tokens_in / 1_000_000 * cin + tokens_out / 1_000_000 * cout, 6)
