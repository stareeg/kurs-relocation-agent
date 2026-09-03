"""Вкладка «Рынок» в вебе: пульс поиска + сетка метрик + метрики воронки + калибровка.

`/pulse`, `/market-grid`, `/search-metrics`: читают снапшот, который фон пересчитывает
каждые `MARKET_SNAPSHOT_INTERVAL_SEC` (`core.domains.market.snapshot_refresh`) — мгновенный ответ
вместо пересчёта на каждый заход. Устаревший снапшот (фон отстал/только поднялся) отдаётся как есть
с `stale=true` (фронт — индикатор «обновляется», не спиннер), не блокирует ответ. Кэша ещё вообще
нет (первый запуск до первого прогона фона / нет PG) → живой расчёт как раньше, попутно кладём
его в кэш.

`/calibration`, `/money`, `/offer-chance-history`, `/api/market/history` — вживую (без снапшота
аналитики); при жалобе на латентность calibration/money добавим в `snapshot_refresh` тем же
приёмом.

M5 (plans/multitenancy_gaps_2026_08_06.md §3.6): `require_account_context` на всех
read-ручках — раньше `market_analytics_snapshot` ключевался только по `kind`, поэтому все
аккаунты делили один кэш и видели аналитику по чужой воронке (S1). `/demand`, `/index` остаются
без аккаунта — объективные показания с публичных страниц hh (`market_demand_readings`/
`market_index_readings`, GLOBAL_REFERENCE), не персональные данные.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.schemas import (
    DemandIngest,
    DemandIngestResponse,
    MarketChatHistory,
    MarketIndexIngest,
    MarketIndexIngestResponse,
)
from api.security import AccountContext, require_account_context
from core.domains.market.market_grid import MarketGrid
from core.domains.market.market_snapshot import (
    MetricHistory,
    MultiHistoryResponse,
    OfferChanceHistory,
)
from core.domains.market.overview import DEFAULT_FROM_DAYS, DEFAULT_TO_DAYS, MarketOverview
from core.domains.market.pulse import MarketPulse
from core.domains.market.relevance import CalibrationReport
from core.domains.market.search_metrics import SearchMetrics
from core.domains.market.service import MoneyOverview
from core.domains.market.snapshot_refresh import is_market_snapshot_stale

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# D-01: новый экран «Рынка» читает один ответ под своим неймспейсом (`/api/market/...`),
# отдельным от `/api/analytics/...`.
market_router = APIRouter(prefix="/api/market", tags=["market"])

_M = TypeVar("_M", bound=BaseModel)


async def _cached_or_live(
    kind: str, model_cls: type[_M], live: Callable[[], Awaitable[_M]], *, account_id: int
) -> _M:
    """Снапшот аккаунта `(account_id, kind)` из `market_analytics_snapshot`, иначе живой расчёт
    (+ бутстрап кэша)."""
    try:
        from core.domains.market.analytics_cache import load_snapshot

        snap = await load_snapshot(kind, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG/таблицы → живой расчёт ниже
        logger.debug("%s: кэш снапшота недоступен (нет PG?): %s", kind, exc)
        snap = None

    if snap is not None:
        try:
            return model_cls.model_validate(snap.payload).model_copy(
                update={
                    "generated_at": snap.computed_at,
                    "stale": is_market_snapshot_stale(snap.computed_at),
                }
            )
        except Exception as exc:  # noqa: BLE001 — битый/устаревший формат кэша → пересчитать
            logger.debug("%s: не разобрал кэш снапшота, считаю вживую: %s", kind, exc)

    try:
        result = await live()
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой отчёт (available=false), не 500
        logger.debug("%s недоступен (нет PG?): %s", kind, exc)
        return model_cls()

    if getattr(result, "available", True):
        try:
            from core.domains.market.analytics_cache import save_snapshot

            await save_snapshot(kind, result.model_dump(mode="json"), account_id=account_id)
        except Exception as exc:  # noqa: BLE001 — бутстрап кэша не критичен для ответа
            logger.debug("%s: снапшот не сохранён (нет PG?): %s", kind, exc)
    return result


@router.get("/pulse", response_model=MarketPulse)
async def get_pulse(
    account: AccountContext = Depends(require_account_context),
) -> MarketPulse:
    """Пульс поиска: единый «Шанс офферов» 0..100 + headline-KPI с суточной динамикой.

    L-25: снапшот из фона (см. модуль docstring); `stale=true` — фон отстал, отдаём как есть.
    Дневной снимок для дельты день-ко-дню (`market_snapshots`) фон пишет сам на каждый прогон —
    на живом фолбэке (кэша ещё нет) дописываем его здесь же, чтобы не терять точку за день.
    """
    from core.domains.market.market_snapshot import record_daily_pulse_state
    from core.domains.market.pulse import get_market_pulse

    account_id = account.account_id

    async def _live() -> MarketPulse:
        pulse = await get_market_pulse(account_id=account_id)
        await record_daily_pulse_state(pulse, account_id=account_id)
        return pulse

    return await _cached_or_live("pulse", MarketPulse, _live, account_id=account_id)


@router.get("/market-grid", response_model=MarketGrid)
async def get_market_grid_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> MarketGrid:
    """Сетка метрик вкладки «Рынок»: один ответ, фиксированный порядок ячеек.

    L-25: снапшот из фона (см. модуль docstring); `stale=true` — фон отстал, отдаём как есть.
    """
    from core.domains.market.market_grid import get_market_grid

    account_id = account.account_id
    return await _cached_or_live(
        "grid",
        MarketGrid,
        lambda: get_market_grid(account_id=account_id),
        account_id=account_id,
    )


@router.get("/search-metrics", response_model=SearchMetrics)
async def get_search_metrics_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> SearchMetrics:
    """Воронка (ступени + медианы), воронка по источникам, пропуски — для виджетов «Рынка».

    L-25: снапшот из фона (см. модуль docstring); `stale=true` — фон отстал, отдаём как есть.
    Нет PG → `available=false`, не 500.
    """
    from core.domains.market.search_metrics import get_search_metrics

    account_id = account.account_id
    return await _cached_or_live(
        "search",
        SearchMetrics,
        lambda: get_search_metrics(account_id=account_id),
        account_id=account_id,
    )


@router.get("/calibration", response_model=CalibrationReport)
async def get_calibration_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> CalibrationReport:
    """«Скоринг не врёт?»: корзины балла × конверсия в скрининг. Нет PG → `available=false`."""
    from core.domains.market.service import get_calibration_report

    return await get_calibration_report(account_id=account.account_id)


@router.get("/money", response_model=MoneyOverview)
async def get_money_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> MoneyOverview:
    """Деньги на рынке: две шкалы + планка резюме + форматы. Нет PG → available=false у половин."""
    from core.domains.market.service import get_money_overview

    return await get_money_overview(account_id=account.account_id)


@router.get("/offer-chance-history", response_model=OfferChanceHistory)
async def get_offer_chance_history_endpoint(
    from_days: int = 30,
    to_days: int = 0,
    account: AccountContext = Depends(require_account_context),
) -> OfferChanceHistory:
    """Спарклайн шанса офферов: суточные снимки за окно (кламп 7…180). <2 точек → available=false.

    `from_days`/`to_days` — обе границы шкалы периода (план 2026-08-03), «дней назад от сегодня».
    """
    from core.domains.market.market_snapshot import get_offer_chance_history

    return await get_offer_chance_history(
        account_id=account.account_id, from_days=from_days, to_days=to_days
    )


@market_router.get("/history", response_model=MetricHistory)
async def get_metric_history_endpoint(
    metric: str,
    from_days: int = 30,
    to_days: int = 0,
    account: AccountContext = Depends(require_account_context),
) -> MetricHistory:
    """История произвольной величины «Рынка» по дневным снимкам: `?metric=hr_response`,
    `?metric=avg_fit`, `?metric=offer_chance_score` и т.п. — headline-KPI и агрегаты верхнего
    уровня из `market_snapshots`. `get_offer_chance_history` — частный случай этой же сборки.
    """
    from core.domains.market.market_snapshot import get_metric_history

    return await get_metric_history(
        metric, account_id=account.account_id, from_days=from_days, to_days=to_days
    )


@market_router.get("/overview", response_model=MarketOverview)
async def get_market_overview_endpoint(
    from_days: int = DEFAULT_FROM_DAYS,
    to_days: int = DEFAULT_TO_DAYS,
    account: AccountContext = Depends(require_account_context),
) -> MarketOverview:
    """Единый ответ «Рынка»: деньги, шанс офферов, что режет поток, воронка двумя уровнями,
    причины отсева — один запрос вместо шести (`/pulse`, `/market-grid`, `/search-metrics`,
    `/money`, ...). Части без источника данных сегодня (индекс рынка, спрос по выдаче, контрфакты
    на гейтах, возраст в этапах) — честный `available=False`, следующие шаги трека D наполняют их
    той же формой ответа. Живой расчёт (кэш снапшота — отдельным шагом, если понадобится).

    `from_days`/`to_days` — шкала периода (план 2026-08-03): обе границы двигаются, правая по
    умолчанию на сегодняшнем дне.
    """
    from core.domains.market.overview import get_market_overview

    clamped_from = max(1, min(from_days, 365))
    clamped_to = max(0, min(to_days, clamped_from - 1))
    return await get_market_overview(
        account_id=account.account_id, from_days=clamped_from, to_days=clamped_to
    )


@market_router.get("/history/multi", response_model=MultiHistoryResponse)
async def get_multi_history_endpoint(
    metrics: str = "funnel,gates,money,formats",
    from_days: int = 30,
    to_days: int = 0,
    account: AccountContext = Depends(require_account_context),
) -> MultiHistoryResponse:
    """Набор групп серий истории «Рынка» во времени одним запросом (для линейных графиков справа
    на вкладке «Рынок»). `metrics` — список групп через запятую: `funnel`/`gates`/`money`/`formats`.

    Расширенный payload (funnel/gates/money) пишется фоном в `market_snapshots` с момента деплоя
    этой правки — первые ~2 недели серии будут короткими, дальше накапливается. Снимки без
    расширенных ключей (старые) читаются корректно (нет ключа → нет точек), без ошибок.
    """
    from core.domains.market.market_snapshot import get_multi_history

    groups = tuple(g.strip() for g in metrics.split(",") if g.strip())
    return await get_multi_history(
        account_id=account.account_id,
        groups=groups,
        from_days=from_days,
        to_days=to_days,
    )


@market_router.post("/demand", response_model=DemandIngestResponse)
async def ingest_market_demand(body: DemandIngest) -> DemandIngestResponse:
    """Принять показание «Найдено N вакансий» со страницы выдачи hh.

    Дневная идемпотентность — upsert в репозитории (день+запрос+источник), не 500 без PG:
    расширение шлёт на каждый заход, не должно спамить ошибками.
    """
    try:
        from core.domains.market.external_signals import save_demand_reading

        reading = await save_demand_reading(body.query, body.count, source=body.source)
    except Exception as exc:  # noqa: BLE001 — нет PG → показание не записано, не 500
        logger.debug("market-demand: показание не сохранено (нет PG?): %s", exc)
        return DemandIngestResponse(persisted=False)
    return DemandIngestResponse(persisted=True, day=reading.day, count=reading.count)


@market_router.post("/index", response_model=MarketIndexIngestResponse)
async def ingest_market_index(body: MarketIndexIngest) -> MarketIndexIngestResponse:
    """Принять месячный индекс «резюме на вакансию» — расширение снимает его со
    страницы статистики hh при визите владельца (правка 2026-08-04 убрала ручной ввод из
    «Параметров»). Идемпотентность — upsert по месяцу."""
    try:
        from core.domains.market.external_signals import save_market_index_reading, zone_for_index

        reading = await save_market_index_reading(body.value, source=body.source)
    except Exception as exc:  # noqa: BLE001 — нет PG → показание не записано, не 500
        logger.debug("market-index: показание не сохранено (нет PG?): %s", exc)
        return MarketIndexIngestResponse(persisted=False)
    return MarketIndexIngestResponse(
        persisted=True,
        month=reading.month.isoformat()[:7],
        value=reading.value,
        zone=zone_for_index(reading.value),
    )


@market_router.get("/chat", response_model=MarketChatHistory)
async def get_market_chat(
    account: AccountContext = Depends(require_account_context),
) -> MarketChatHistory:
    """История чата по ситуации на рынке аккаунта запроса (хронологически). Нет PG → пустой список.

    Заменил бывший блок «Что сделать» (next-steps) на свободный диалог с карьерным стратегом:
    история переживает переход между разделами и перезагрузку (market_chat_messages).
    `attachments`/`reply_to_message_id` (2026-08-11, Заход 6 п.7) — паритет с чатом по вакансии.
    """
    from api.routers.market.mappers import market_chat_history
    from core.domains.assistant.attachments.service import load_for_market_chat_messages
    from core.domains.market.market_chat import load_market_chat

    messages = await load_market_chat(account_id=account.account_id)
    message_ids = [m.id for m in messages if m.id is not None]
    attachments = await load_for_market_chat_messages(message_ids, account_id=account.account_id)
    return market_chat_history(messages, attachments)


@market_router.delete("/chat")
async def clear_market_chat_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> dict[str, int]:
    """Очистить чат по ситуации на рынке аккаунта запроса. Возвращает число удалённых строк."""
    from core.domains.market.market_chat import clear_market_chat

    removed = await clear_market_chat(account_id=account.account_id)
    return {"removed": removed}


@market_router.delete("/chat/messages/{message_id}")
async def delete_market_chat_message_endpoint(
    message_id: int,
    account: AccountContext = Depends(require_account_context),
) -> dict[str, bool]:
    """Удалить одну реплику (выделение → Удалить, зеркало `DELETE /{vacancy_id}/messages/{id}`
    чата по вакансии)."""
    from core.domains.market.market_chat import delete_market_chat_messages

    removed = await delete_market_chat_messages([message_id], account_id=account.account_id)
    return {"deleted": removed > 0}
