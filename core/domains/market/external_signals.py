"""Внешние показания рынка: спрос по выдаче hh и месячный индекс «резюме на
вакансию» — снимает расширение со страниц, которые владелец и так открывает, без единого
серверного запроса к hh (план market_redesign_v3, п.2.6, «чего не делаем ни при каких условиях»).

Идемпотентность — upsert по естественному ключу (день+запрос+источник / месяц), не дедуп на
стороне расширения: повторный заход в те же сутки/тот же месяц обновляет значение, а не плодит
строку (готовность D-07).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

DEFAULT_DEMAND_SOURCE = "hh_serp"
DEFAULT_INDEX_SOURCE = "hh_stats"

# Зоны индекса «резюме на вакансию» (план п.2.6.3): до 4 — рынок соискателя, 5–7 — равновесие,
# 8–11.9 — высокая конкуренция, 12 и выше — крайне высокая.
_INDEX_ZONES: tuple[tuple[float, str], ...] = (
    (4.0, "рынок соискателя"),
    (7.0, "равновесие"),
    (11.9, "высокая конкуренция"),
)
_INDEX_ZONE_HIGH = "крайне высокая конкуренция"


def zone_for_index(value: float) -> str:
    """Значение индекса «резюме на вакансию» → название зоны (план п.2.6.3)."""
    for ceiling, label in _INDEX_ZONES:
        if value <= ceiling:
            return label
    return _INDEX_ZONE_HIGH


def normalize_query(text: str) -> str:
    """Нормализация поискового запроса для дедупа: нижний регистр, схлопнутые пробелы."""
    return re.sub(r"\s+", " ", text.strip().lower())


class DemandReading(BaseModel):
    """Одно дневное показание «сколько вакансий по запросу»."""

    id: int | None = None
    day: date
    query: str
    count: int
    source: str = DEFAULT_DEMAND_SOURCE
    captured_at: datetime | None = None


class MarketIndexReading(BaseModel):
    """Одно месячное показание индекса «резюме на вакансию» — снимается расширением со
    страницы статистики hh (правка 2026-08-04 убрала ручной ввод из «Параметров»)."""

    id: int | None = None
    month: date
    value: float
    source: str = DEFAULT_INDEX_SOURCE
    captured_at: datetime | None = None


def _today() -> date:
    return datetime.now(UTC).date()


def _month_start(day: date | None = None) -> date:
    return (day or _today()).replace(day=1)


async def save_demand_reading(
    query: str,
    count: int,
    *,
    source: str = DEFAULT_DEMAND_SOURCE,
    db: Executor | None = None,
) -> DemandReading:
    """Записать показание спроса. Дневная идемпотентность: upsert по (день, запрос, источник)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into market_demand_readings (day, query, count, source, captured_at) "
        "values ($1, $2, $3, $4, now()) "
        "on conflict (day, query, source) do update "
        "set count = excluded.count, captured_at = excluded.captured_at "
        "returning id, day, query, count, source, captured_at",
        _today(),
        normalize_query(query),
        count,
        source,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return DemandReading(**row_to_dict(row))


async def get_latest_market_index(*, db: Executor | None = None) -> MarketIndexReading | None:
    """Последний по месяцу индекс «резюме на вакансию» — для отображения на «Рынке»."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select id, month, value, source, captured_at from market_index_readings "
        "order by month desc limit 1"
    )
    return MarketIndexReading(**row_to_dict(row)) if row is not None else None


async def save_market_index_reading(
    value: float,
    *,
    source: str = DEFAULT_INDEX_SOURCE,
    db: Executor | None = None,
) -> MarketIndexReading:
    """Записать месячный индекс рынка. Идемпотентность: upsert по месяцу."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into market_index_readings (month, value, source, captured_at) "
        "values ($1, $2, $3, now()) "
        "on conflict (month) do update "
        "set value = excluded.value, source = excluded.source, captured_at = excluded.captured_at "
        "returning id, month, value, source, captured_at",
        _month_start(),
        value,
        source,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return MarketIndexReading(**row_to_dict(row))


__all__ = [
    "DEFAULT_DEMAND_SOURCE",
    "DEFAULT_INDEX_SOURCE",
    "DemandReading",
    "MarketIndexReading",
    "get_latest_market_index",
    "normalize_query",
    "save_demand_reading",
    "save_market_index_reading",
    "zone_for_index",
]
