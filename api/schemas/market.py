"""Транспортные схемы API: market."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from api.schemas.attachments import AttachmentOut
from core.domains.market.market_snapshot import (
    MetricHistory,
    MultiHistoryResponse,
    OfferChanceHistory,
)
from core.domains.market.overview import MarketOverview
from core.domains.market.service import MoneyOverview
from core.domains.market.situation import SituationNarrative

# --- Метрики (агрегаты llm_usage; judge/agent_tasks удалены в R-13/R-14) ---


class UsageByAgent(BaseModel):
    agent: str
    cost_usd: float
    tokens_in: int
    tokens_out: int
    calls: int


class CostByDay(BaseModel):
    """Стоимость LLM по дням (llm_usage), для графика трат на странице метрик."""

    day: str  # ISO-дата
    cost_usd: float


class TierTokenTotals(BaseModel):
    """Токены входа/выхода за период для одного бакета тиров (basic+reserve или advanced)."""

    tokens_in: int = 0
    tokens_out: int = 0


class TokenStats(BaseModel):
    """Токены по тирам — «Сегодня» и «За месяц» (30 дней), для витрины «Параметры»."""

    today_basic: TierTokenTotals = Field(default_factory=TierTokenTotals)
    today_advanced: TierTokenTotals = Field(default_factory=TierTokenTotals)
    month_basic: TierTokenTotals = Field(default_factory=TierTokenTotals)
    month_advanced: TierTokenTotals = Field(default_factory=TierTokenTotals)


class MetricsResponse(BaseModel):
    today_cost_usd: float
    total_cost_usd: float
    token_stats: TokenStats = Field(default_factory=TokenStats)
    usage_by_agent: list[UsageByAgent] = Field(default_factory=list)
    cost_by_day: list[CostByDay] = Field(default_factory=list)


class SituationResponse(BaseModel):
    """Кэш/результат LLM-сводки ситуации «Рынка» (слито с ретро воронки в UX5-20).

    GET отдаёт последнюю сохранённую сводку без LLM-вызова (`generated_at` — когда сгенерирована);
    POST генерирует свежую reasoning-моделью и кладёт в кэш. Нет сводки/нет PG → `available=false`
    и `note` (фронт честный empty с кнопкой «Обновить»), не 500.
    """

    available: bool = False
    narrative: SituationNarrative | None = None
    generated_at: datetime | None = None
    note: str | None = None
    # L-25: сводка обновляется раз в сутки по расписанию — `stale` (кэш старше суточного цикла +
    # запас) включает индикатор «обновляется» на фронте, не блокируя показ последней версии.
    stale: bool = False


# --- Внешние показания рынка: спрос по выдаче hh + месячный индекс ---
# Расширение шлёт сюда с `X-API-Key` то, что уже отрисовано на страницах hh, которые владелец
# и так открывает (план market_redesign_v3, п.2.6) — не серверный запрос к hh.


class DemandIngest(BaseModel):
    """Показание «Найдено N вакансий» со страницы выдачи hh."""

    query: str = Field(min_length=1, max_length=256)
    count: int = Field(ge=0)
    source: str = Field(default="hh_serp", max_length=32)


class DemandIngestResponse(BaseModel):
    """Результат приёма показания спроса. `persisted=false` — PG лежал, не 500."""

    persisted: bool = False
    day: date | None = None
    count: int = 0


class MarketIndexIngest(BaseModel):
    """Месячный индекс «резюме на вакансию» — снимается расширением со страницы
    статистики hh (правка 2026-08-04 убрала ручной ввод из «Параметров»)."""

    value: float = Field(ge=0)
    source: str = Field(default="hh_stats", max_length=32)


class MarketIndexIngestResponse(BaseModel):
    """Результат приёма индекса рынка. `persisted=false` — PG лежал, не 500."""

    persisted: bool = False
    month: str = ""
    value: float | None = None
    zone: str | None = None


# --- Чат по ситуации на рынке (вкладка «Рынок», внизу под графиками) ---
# Лента реплик user/assistant аккаунта. Заменил бывший блок «Что сделать» (next-steps):
# вместо односторонней сводки — свободный диалог с карьерным стратегом. Персист на бэкенде
# (market_chat_messages), история переживает переход между разделами и перезагрузку.


class MarketChatMessageOut(BaseModel):
    """Реплика чата по ситуации на рынке. role: user (владелец) | assistant (LLM).

    `reply_to_message_id`/`attachments` (2026-08-11, Заход 6 п.7) — паритет с чатом по вакансии."""

    id: int
    role: Literal["user", "assistant"]
    content: str
    reply_to_message_id: int | None = None
    attachments: list[AttachmentOut] = Field(default_factory=list)
    created_at: datetime | None = None


class MarketChatHistory(BaseModel):
    """История чата по ситуации на рынке аккаунта запроса (хронологически). Нет PG → []."""

    items: list[MarketChatMessageOut] = Field(default_factory=list)


__all__ = [
    "UsageByAgent",
    "CostByDay",
    "DemandIngest",
    "DemandIngestResponse",
    "MarketChatHistory",
    "MarketChatMessageOut",
    "MarketIndexIngest",
    "MarketIndexIngestResponse",
    "MarketOverview",
    "MetricHistory",
    "MetricsResponse",
    "MoneyOverview",
    "MultiHistoryResponse",
    "OfferChanceHistory",
    "SituationResponse",
]
