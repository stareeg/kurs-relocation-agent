"""Cost-учёт LLM в Postgres (задача 1.1, подшаг 5) — заменяет JSONL из 0.2.

`PostgresUsageSink` реализует синхронный протокол `UsageSink` (его дёргает
OpenRouterChatModel из async-кода). Запись делаем fire-and-forget задачей в текущем
event loop, чтобы не блокировать LLM-вызов; сумму за день держим в памяти (warmup при
старте + инкремент на каждом record) — она нужна только для мягкого budget-гейта (В8.7),
точность до цента не критична. Чистые async-функции insert_usage/day_cost тестируются
напрямую против пула.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from pydantic import BaseModel, Field

from core.config import current_account_id
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)


async def insert_usage(
    agent: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost: float,
    *,
    tier: str = "basic",
    day: date | None = None,
    ttfb_ms: int | None = None,
    total_ms: int | None = None,
    queue_ms: int | None = None,
    attempt: int | None = None,
    cache_hit: bool = False,
    account_id: int | None = None,
    db: Executor | None = None,
) -> None:
    executor = db if db is not None else get_pool()
    cols = (
        "agent, model, tokens_in, tokens_out, cost_usd, "
        "ttfb_ms, total_ms, queue_ms, attempt, cache_hit, account_id, tier"
    )
    vals = (
        agent,
        model,
        int(tokens_in),
        int(tokens_out),
        cost,
        ttfb_ms,
        total_ms,
        queue_ms,
        attempt,
        bool(cache_hit),
        account_id,
        tier,
    )
    if day is None:
        await executor.execute(
            f"insert into llm_usage ({cols}) "
            "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)",
            *vals,
        )
    else:
        await executor.execute(
            f"insert into llm_usage ({cols}, day) "
            "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
            *vals,
            day,
        )


async def day_cost(day: date | None = None, *, db: Executor | None = None) -> float:
    executor = db if db is not None else get_pool()
    target = day or date.today()
    value = await executor.fetchval(
        "select coalesce(sum(cost_usd), 0)::float8 from llm_usage where day = $1", target
    )
    return round(float(value or 0.0), 6)


class AgentUsage(BaseModel):
    """Строка витрины «сколько потратил агент» (`/api/metrics`)."""

    agent: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    calls: int


class DayCost(BaseModel):
    """Стоимость за календарный день (для графика)."""

    day: str
    cost_usd: float


class TierTokenTotals(BaseModel):
    """Токены входа/выхода за период для одного тира (или бакета тиров)."""

    tokens_in: int = 0
    tokens_out: int = 0


class UsageMetrics(BaseModel):
    """Агрегаты `llm_usage`. Нет Postgres → нули и пустые списки, витрина не падает."""

    today_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    # Токены по тирам — блок статистики на «Параметрах» различает «сегодня»/«за месяц» и
    # «базовые» (basic + reserve, резерв пока не используется, но логически тот же бакет)
    # / «продвинутые» (advanced).
    today_basic: TierTokenTotals = Field(default_factory=TierTokenTotals)
    today_advanced: TierTokenTotals = Field(default_factory=TierTokenTotals)
    month_basic: TierTokenTotals = Field(default_factory=TierTokenTotals)
    month_advanced: TierTokenTotals = Field(default_factory=TierTokenTotals)
    usage_by_agent: list[AgentUsage] = []
    cost_by_day: list[DayCost] = []


async def load_usage_metrics(
    account_id: int, *, db: Executor | None = None, days: int = 60
) -> UsageMetrics:
    """Витрина расходов на LLM аккаунта: сумма всего / за сегодня, токены по тирам, разрез по
    агентам и по дням.

    Строго по `account_id` — решение владельца 2026-08-06 (plans/multitenancy_gaps_2026_08_06.md
    §3.8, §9 п.3): без операторского исключения, «эта ручка отвечает про меня» для всех,
    включая владельца. Строки без атрибуции (account_id is null — LLM-вызовы вне request/task-
    контекста) не попадают никому, тот же принцип, что бандл логов.
    """
    metrics = UsageMetrics()
    try:
        pool = db or get_pool()
        metrics.total_cost_usd = round(
            float(
                await pool.fetchval(
                    "select coalesce(sum(cost_usd),0)::float8 from llm_usage where account_id = $1",
                    account_id,
                )
            ),
            6,
        )
        metrics.today_cost_usd = round(
            float(
                await pool.fetchval(
                    "select coalesce(sum(cost_usd),0)::float8 "
                    "from llm_usage where account_id = $1 and day = current_date",
                    account_id,
                )
            ),
            6,
        )
        # Токены по тирам, сегодня и за 30 дней одним проходом — окно за 30 дней покрывает
        # и «сегодня» (FILTER), индекс (account_id, tier, day) закрывает where+group by.
        tier_rows = await pool.fetch(
            "select tier, "
            "coalesce(sum(tokens_in) filter (where day = current_date),0)::bigint as today_ti, "
            "coalesce(sum(tokens_out) filter (where day = current_date),0)::bigint as today_too, "
            "coalesce(sum(tokens_in),0)::bigint as month_ti, "
            "coalesce(sum(tokens_out),0)::bigint as month_too "
            "from llm_usage "
            "where account_id = $1 and day > current_date - interval '30 days' "
            "group by tier",
            account_id,
        )
        for r in tier_rows:
            # Резервный тир пока не используется продуктом, но по смыслу — тот же бакет,
            # что «базовые» (см. LlmFeature.tier в core/platform/llm/registry.py).
            advanced = r["tier"] == "advanced"
            today_bucket = metrics.today_advanced if advanced else metrics.today_basic
            month_bucket = metrics.month_advanced if advanced else metrics.month_basic
            today_bucket.tokens_in += int(r["today_ti"])
            today_bucket.tokens_out += int(r["today_too"])
            month_bucket.tokens_in += int(r["month_ti"])
            month_bucket.tokens_out += int(r["month_too"])
        rows = await pool.fetch(
            "select agent, sum(cost_usd)::float8 cost, sum(tokens_in)::bigint ti, "
            "sum(tokens_out)::bigint too, count(*)::bigint calls from llm_usage "
            "where account_id = $1 group by agent order by cost desc",
            account_id,
        )
        metrics.usage_by_agent = [
            AgentUsage(
                agent=r["agent"],
                cost_usd=round(float(r["cost"]), 6),
                tokens_in=int(r["ti"]),
                tokens_out=int(r["too"]),
                calls=int(r["calls"]),
            )
            for r in rows
        ]
        # alias не `day`: ключевое слово PG (interval ... day), в позиции алиаса = syntax error.
        day_rows = await pool.fetch(
            "select day::text as d, sum(cost_usd)::float8 as c from llm_usage "
            f"where account_id = $1 group by day order by day desc limit {max(1, int(days))}",
            account_id,
        )
        # фронту нужен хронологический порядок (старые слева)
        metrics.cost_by_day = [
            DayCost(day=r["d"], cost_usd=round(float(r["c"]), 6)) for r in reversed(day_rows)
        ]
    except Exception as exc:  # noqa: BLE001 — нет PG/таблицы → нули, витрина не 500
        logger.debug("llm_usage метрики недоступны (нет PG?): %s", exc)
    return metrics


class PostgresUsageSink:
    """UsageSink на Postgres. Активна только под долгоживущим loop API (lifespan ставит
    её дефолтным синком); вне loop запись пропускается с предупреждением."""

    def __init__(self, pool: Executor) -> None:
        self._pool = pool
        self._day = date.today()
        self._today_cost = 0.0
        self._tasks: set[asyncio.Task] = set()

    async def warmup(self) -> None:
        """Подтянуть сумму за сегодня из БД (после рестарта budget-гейт корректен)."""
        self._day = date.today()
        self._today_cost = await day_cost(self._day, db=self._pool)

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._day:
            self._day = today
            self._today_cost = 0.0

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
        self._roll_day()
        self._today_cost += float(cost)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("PostgresUsageSink.record вне event loop — insert пропущен")
            return
        # Читаем ContextVar синхронно, ЗДЕСЬ (личность вызывающего), а не внутри спавненной
        # задачи — явная передача надёжнее, чем полагаться на то, что asyncio.Task унаследует
        # контекст создателя (§3.8: LLM-usage должен приписываться аккаунту запроса/фон-задачи,
        # а не последнему, кто установил ContextVar к моменту фактического insert).
        account_id = current_account_id()
        task = loop.create_task(
            self._safe_insert(
                agent,
                model,
                tokens_in,
                tokens_out,
                cost,
                self._day,
                tier=tier,
                ttfb_ms=ttfb_ms,
                total_ms=total_ms,
                queue_ms=queue_ms,
                attempt=attempt,
                cache_hit=cache_hit,
                account_id=account_id,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _safe_insert(
        self,
        agent: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        day: date,
        *,
        tier: str = "basic",
        ttfb_ms: int | None = None,
        total_ms: int | None = None,
        queue_ms: int | None = None,
        attempt: int | None = None,
        cache_hit: bool = False,
        account_id: int | None = None,
    ) -> None:
        try:
            await insert_usage(
                agent,
                model,
                tokens_in,
                tokens_out,
                cost,
                tier=tier,
                day=day,
                ttfb_ms=ttfb_ms,
                total_ms=total_ms,
                queue_ms=queue_ms,
                attempt=attempt,
                cache_hit=cache_hit,
                account_id=account_id,
                db=self._pool,
            )
        except Exception as exc:  # учёт не должен ронять LLM-путь
            logger.warning("PostgresUsageSink: insert не удался: %s", exc)

    def today_cost_usd(self) -> float:
        self._roll_day()
        return round(self._today_cost, 6)
