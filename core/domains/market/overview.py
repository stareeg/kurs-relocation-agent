"""Единый ответ вкладки «Рынок» (план D-01): деньги, шанс офферов, что режет поток, воронка
двумя уровнями, причины отсева — одним запросом вместо шести (`/pulse`, `/market-grid`,
`/search-metrics`, `/money`, ...).

`get_market_overview` — сборка поверх уже существующих чистых расчётов домена (`pulse`,
`service.get_money_overview`, `search_metrics`, `stage_aging`, `external_signals` — E-03). Части,
для которых источника данных ещё нет (спрос по выдаче hh — E-01), отдаются честным
`available=False`/пустым списком — следующие шаги трека E наполняют их, не меняя форму ответа
(совпадает с духом `enough_data`/`available` по всему домену).

`compute_overview_funnel` — двухуровневая воронка (правка 2.3 плана): у каждой строки своя
подписанная база, сегменты в сумме дают базу без остатка. Первая строка — все отклики, вторая —
только те, что сейчас в работе (это её база = сегмент «в работе» первой строки).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from core.domains.market.external_signals import get_latest_market_index, zone_for_index
from core.domains.market.market import MarketBucket
from core.domains.market.pulse import GateCounterfactuals, OfferChance, get_market_pulse
from core.domains.market.relevance import KillFactor
from core.domains.market.search_metrics import SkipReasonCount, get_search_metrics
from core.domains.market.service import MoneyOverview, get_money_overview
from core.domains.market.stage_aging import StageAging, compute_stage_aging
from core.domains.pipeline.analytics import compute_funnel_analytics
from core.domains.pipeline.hr_threads import count_threads_active_in_period
from core.kernel.schemas.funnel import FunnelStatus, resolve_funnel_status
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

DEFAULT_OVERVIEW_DAYS = 30

# Диапазон периода «Рынка» (план 2026-08-03, шкала вместо дискретных чипов): обе границы —
# «дней назад от сегодня», правая по умолчанию на сегодняшнем дне.
DEFAULT_FROM_DAYS = 14
DEFAULT_TO_DAYS = 0

# Риск 3 плана: значение индекса рынка вводится раз в месяц вручную и может протухнуть, если
# владелец забудет — старше двух месяцев считаем непоказательным и прячем блок, а не врём датой.
_MARKET_INDEX_MAX_AGE_DAYS = 62

# Правка 2026-08-04: если с последнего скоринга прошло больше этого числа дней, считаем, что цикл
# поиска встал/начался заново — не тянем древнюю историю на шкалу периода, просто ждём новую
# первую заскоренную вакансию (см. `_load_history_start_days`).
_HISTORY_RESTART_GAP_DAYS = 90

# Ступени, которые считаются «в работе» — второй строкой двухуровневой воронки, в этом порядке.
_ACTIVE_STAGES: tuple[tuple[FunnelStatus, str], ...] = (
    (FunnelStatus.SCREENING, "скрининг"),
    (FunnelStatus.TECH, "техничка"),
    (FunnelStatus.FINAL, "финал"),
    (FunnelStatus.OFFER, "оффер"),
)
_ACTIVE_STAGE_VALUES: frozenset[str] = frozenset(s.value for s, _ in _ACTIVE_STAGES)

# Столбики периодной «Воронки» (2.4, короткие подписи для CategoryBars) — четыре стадии из полного
# списка ступеней + диалоги. Диалоги — базовая корзина (100%): от неё считаются доли Скринингов/
# Техничек/Финалов, а не от суммы всех корзин, как раньше (правка 2026-08-14: «честнее считать
# конверсию от того, что реально завязалось, чем от микса этапов и диалогов»).
_PERIOD_STAGES: tuple[tuple[FunnelStatus, str], ...] = (
    (FunnelStatus.SCREENING, "Скрининги"),
    (FunnelStatus.TECH, "Технички"),
    (FunnelStatus.FINAL, "Финалы"),
    (FunnelStatus.OFFER, "Офферы"),
)
# Диалоги добавляются отдельным bucket вызывающим (`get_market_overview`) — см. `count_threads_-
# active_in_period`. Базовая корзина воронки: от её counts считаются pct всех остальных.
_DIALOGS_LABEL = "Диалоги"


class FunnelLevelSegment(BaseModel):
    """Один сегмент строки воронки: подпись, число, доля от базы своей строки (0..100)."""

    key: str
    label: str
    count: int
    pct: float = 0.0


class FunnelLevel(BaseModel):
    """Одна строка двухуровневой воронки (2.3): своя база в подписи, сегменты дают базу без остатка."""

    label: str
    base: int = 0
    segments: list[FunnelLevelSegment] = Field(default_factory=list)


class MarketIndexPoint(BaseModel):
    """Индекс рынка «резюме на вакансию»: тихо снимается расширением со страницы
    статистики hh при визите владельца (правка 2026-08-04 убрала ручной ввод из «Параметров» —
    поле легко читается со страницы, дублировать его руками незачем). Нет ни одного показания,
    либо последнее старше двух месяцев (план, риск 3 — «прятать блок, а не показывать
    протухшее») — `available=False`."""

    available: bool = False
    value: float | None = None
    zone: str | None = None
    captured_at: datetime | None = None


class DemandPoint(BaseModel):
    """Одно недельное показание «сколько вакансий по моему запросу»."""

    week: str
    count: int


class DemandTrend(BaseModel):
    """Спрос по выдаче hh, вакансий в неделю: копит расширение. Источника ещё нет —
    `available=False`, точки появятся без изменения формы ответа."""

    available: bool = False
    points: list[DemandPoint] = Field(default_factory=list)


class GatesOverview(BaseModel):
    """«Что режет поток»: топ-4 критерия отбора (из `pulse.kill_factors`) + свои пропуски +
    контрфакты на жёстких гейтах (`pulse.gate_counterfactuals`): сколько проходит сейчас и
    сколько прошло бы при смягчении зарплаты/формата — без LLM, пересчёт по сохранённым оценкам.

    Гейты не эксклюзивны — вакансия может упасть сразу по двум, поэтому `kill_factors` не
    суммируются в `total_scored`. `breakdown` — отдельная взаимоисключающая сегментация
    той же вселенной (`pulse.gate_breakdown`): каждая заскоренная вакансия ровно в одном сегменте
    (передана оба гейта / упала по первому сработавшему критерию по приоритету зарплата → формат
    → грейд → роль), сумма сегментов = число заскоренных не пропущенных владельцем вручную
    вакансий. `self_skipped` — свои пропуски, отдельная база, не входит в сумму `breakdown`.
    """

    total_scored: int = 0
    self_skipped: int = 0
    kill_factors: list[KillFactor] = Field(default_factory=list)
    counterfactuals: GateCounterfactuals = Field(default_factory=GateCounterfactuals)
    breakdown: list[KillFactor] = Field(default_factory=list)


class MarketOverview(BaseModel):
    """Ответ `GET /api/market/overview`: всё, что рисует экран «Рынок», одним запросом.

    Нет заскоренных вакансий / нет PG → `available=False`, блоки — честный empty (не 500),
    как и весь остальной домен `market`.
    """

    available: bool = False
    days: int = DEFAULT_OVERVIEW_DAYS
    from_days: int = DEFAULT_FROM_DAYS
    to_days: int = DEFAULT_TO_DAYS
    generated_at: datetime | None = None
    # Дней до первой заскоренной вакансии — динамическая левая граница шкалы периода (правка
    # 2026-08-04): без фиксированных 90 дней, всегда от реального начала истории. `None`, если
    # вакансий ещё не было, либо последний скоринг старше `_HISTORY_RESTART_GAP_DAYS` (цикл поиска
    # считается начавшимся заново — фронт просто ждёт новую первую).
    history_start_days: int | None = None
    money: MoneyOverview = Field(default_factory=MoneyOverview)
    market_index: MarketIndexPoint = Field(default_factory=MarketIndexPoint)
    demand: DemandTrend = Field(default_factory=DemandTrend)
    offer_chance: OfferChance = Field(default_factory=OfferChance)
    gates: GatesOverview = Field(default_factory=GatesOverview)
    funnel: list[FunnelLevel] = Field(default_factory=list)
    # Плоские столбики «Воронки» шкалой периода (2026-08-11): сколько вакансий ВПЕРВЫЕ
    # дошли до стадии в [from_days; to_days] + сколько диалогов было активно — в отличие от
    # `funnel` (снимок текущего статуса, без периода), эти четыре числа отвечают на «что
    # произошло за выбранный период», а не «как распределены вакансии сейчас».
    funnel_period: list[MarketBucket] = Field(default_factory=list)
    dropout_reasons: list[SkipReasonCount] = Field(default_factory=list)
    # «Форматы работы» совмещённая визуализация (2026-08-11): Грейд/Роль рядом с уже
    # существующим `money.supply.work_formats` (Формат) — те же заскоренные вакансии, что
    # кормят «Шанс офферов» (переиспользуем уже посчитанный `pulse`, без второго запроса).
    grade_levels: list[MarketBucket] = Field(default_factory=list)
    role_niches: list[MarketBucket] = Field(default_factory=list)
    stage_aging: StageAging = Field(default_factory=StageAging)


def _pct(numer: int, denom: int) -> float:
    return round(100 * numer / denom, 1) if denom else 0.0


def compute_overview_funnel(
    *,
    applied_total: int,
    active_statuses: list[str | None],
) -> list[FunnelLevel]:
    """Двухуровневая воронка из уже готовых чисел. Чистая — тестируется без БД.

    `applied_total` — сколько вакансий хотя бы раз дошли до «Отклик» (см.
    `FunnelAnalytics.applied`). `active_statuses` — текущий статус каждой не пропущенной
    вакансии; из них считаем только тех, кто сейчас в активной стадии (скрининг и дальше).
    Всё остальное (тишина, а также отказ после любого прогресса) — один честный сегмент
    «без ответа», без деления на «было/не было» — это и есть первая правка 2.3 плана.
    """
    if applied_total <= 0:
        return []

    stage_counts: Counter[str] = Counter()
    for status in active_statuses:
        resolved = resolve_funnel_status(status)
        if resolved in _ACTIVE_STAGE_VALUES:
            stage_counts[resolved] += 1

    in_progress = sum(stage_counts.values())
    no_answer = max(0, applied_total - in_progress)

    responses_row = FunnelLevel(
        label="Отклики",
        base=applied_total,
        segments=[
            FunnelLevelSegment(
                key="no_answer",
                label="без ответа",
                count=no_answer,
                pct=_pct(no_answer, applied_total),
            ),
            FunnelLevelSegment(
                key="in_progress",
                label="в работе",
                count=in_progress,
                pct=_pct(in_progress, applied_total),
            ),
        ],
    )
    if in_progress == 0:
        return [responses_row]

    in_progress_row = FunnelLevel(
        label="В работе",
        base=in_progress,
        segments=[
            FunnelLevelSegment(
                key=stage.value,
                label=label,
                count=stage_counts.get(stage.value, 0),
                pct=_pct(stage_counts.get(stage.value, 0), in_progress),
            )
            for stage, label in _ACTIVE_STAGES
        ],
    )
    return [responses_row, in_progress_row]


def compute_period_funnel_bars(
    *,
    stages: list[tuple[int, str, datetime]],
    period_start: datetime,
    period_end: datetime,
) -> list[MarketBucket]:
    """Столбики «Скрининги / Технички / Финалы / Офферы» за период: сколько РАЗНЫХ вакансий получили
    переход на эту стадию внутри `[period_start; period_end]` — не текущий статус (`funnel`
    выше), а факт активности за окно. Чистая — тестируется без БД, `stages` уже отфильтрован
    вызывающим до не пропущенных вакансий (см. `get_market_overview`).

    Возвращает ВСЕ четыре корзины в фиксированном порядке (`_PERIOD_STAGES`), включая нулевые —
    так фронт рисует полный столбцовый ряд без дыр (правка 2026-08-14: раньше нулевые корзины
    выпадали, и ряд «прыгал» при появлении/исчезновении стадии).

    `pct` здесь — доля от числа самих достигнутых стадий (внутренняя база среза). Это значение
    фронт НЕ использует для столбцов воронки: вызывающий (`get_market_overview`) пересчитывает
    `pct` от числа Диалогов (базовая корзня воронки) — см. `_DIALOGS_LABEL`. Здесь же `pct`
    остаётся только для обратной совместимости тестов/старых чтений.
    """
    # DISTINCT job_id на стадию — одна и та же вакансия может дважды войти в скрининг за период
    # (вернулась после паузы), считаем вакансию, а не событие.
    stage_jobs: dict[str, set[int]] = {}
    for job_id, stage, changed_at in stages:
        at = changed_at if changed_at.tzinfo else changed_at.replace(tzinfo=UTC)
        if at < period_start or at > period_end:
            continue
        resolved = resolve_funnel_status(stage)
        if resolved is not None:
            stage_jobs.setdefault(resolved, set()).add(job_id)

    total = len(
        set().union(*(stage_jobs.get(s.value, set()) for s, _ in _PERIOD_STAGES)) or [set()]
    )
    return [
        MarketBucket(
            label=label,
            count=len(stage_jobs.get(stage.value, set())),
            pct=_pct(len(stage_jobs.get(stage.value, set())), total),
        )
        for stage, label in _PERIOD_STAGES
    ]


async def _load_market_index(*, db: Executor) -> MarketIndexPoint:
    """Последнее показание индекса рынка → `MarketIndexPoint`, либо честный empty."""
    try:
        reading = await get_latest_market_index(db=db)
    except Exception as exc:  # noqa: BLE001 — таблицы ещё нет / нет PG → пустой блок, не 500
        logger.debug("market-overview: индекс рынка недоступен: %s", exc)
        return MarketIndexPoint()

    if reading is None:
        return MarketIndexPoint()

    age_days = (datetime.now(UTC) - reading.captured_at).days if reading.captured_at else None
    if age_days is not None and age_days > _MARKET_INDEX_MAX_AGE_DAYS:
        return MarketIndexPoint()

    return MarketIndexPoint(
        available=True,
        value=reading.value,
        zone=zone_for_index(reading.value),
        captured_at=reading.captured_at,
    )


async def _load_history_start_days(*, account_id: int, db: Executor) -> int | None:
    """Дней от сегодня до первой заскоренной вакансии аккаунта, либо `None` (пусто / цикл поиска
    начался заново — см. `_HISTORY_RESTART_GAP_DAYS`)."""
    try:
        row = await db.fetchrow(
            "select min(scored_at) as first_at, max(scored_at) as last_at "
            "from jobs where account_id = $1 and scored_at is not null",
            account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG/таблицы → честный None, не 500
        logger.debug("market-overview: история скоринга недоступна: %s", exc)
        return None

    if row is None or row["first_at"] is None or row["last_at"] is None:
        return None

    now = datetime.now(UTC)
    last_at = row["last_at"] if row["last_at"].tzinfo else row["last_at"].replace(tzinfo=UTC)
    if (now - last_at).days > _HISTORY_RESTART_GAP_DAYS:
        return None

    first_at = row["first_at"] if row["first_at"].tzinfo else row["first_at"].replace(tzinfo=UTC)
    return max(1, (now - first_at).days)


async def get_market_overview(
    *,
    account_id: int,
    db: Executor | None = None,
    from_days: int = DEFAULT_FROM_DAYS,
    to_days: int = DEFAULT_TO_DAYS,
) -> MarketOverview:
    """Собрать единый ответ «Рынка» аккаунта из Postgres. Read-only, без LLM.

    Переиспользует уже существующие сборки (`pulse`, `money`, `search-metrics`) — не дублирует их
    запросы. Нет PG / нет заскоренных вакансий → `available=False`, как у остальных отчётов домена.

    `from_days`/`to_days` — обе границы шкалы периода («дней назад от сегодня»); сохраняются в
    ответе для отображения на шкале. Сами `pulse`/`money`/`search-metrics` период пока не
    учитывают (см. план, трек D-02 — не входит в этот шаг).
    """
    days = max(1, from_days - to_days)
    try:
        pool = db
        if pool is None:
            from core.platform.db.pool import get_pool

            pool = get_pool()
    except Exception as exc:  # noqa: BLE001 — нет PG → available=False, не 500
        logger.debug("market-overview недоступен (нет PG?): %s", exc)
        return MarketOverview(days=days, from_days=from_days, to_days=to_days)

    try:
        pulse, money, search = await asyncio.gather(
            get_market_pulse(account_id=account_id, db=pool, from_days=from_days, to_days=to_days),
            get_money_overview(account_id=account_id, db=pool),
            get_search_metrics(account_id=account_id, db=pool),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("market-overview: базовые отчёты недоступны: %s", exc)
        return MarketOverview(days=days, from_days=from_days, to_days=to_days)

    market_index, history_start_days = await asyncio.gather(
        _load_market_index(db=pool), _load_history_start_days(account_id=account_id, db=pool)
    )

    now = datetime.now(UTC)
    period_start = now - timedelta(days=from_days)
    period_end = now - timedelta(days=to_days)

    funnel: list[FunnelLevel] = []
    funnel_period: list[MarketBucket] = []
    aging = StageAging()
    try:
        job_rows = await pool.fetch(
            "select id, status, company, title, overall_score, "
            "exists(select 1 from skipped_vacancies sv where sv.vacancy_id = jobs.vacancy_id "
            "and sv.account_id = jobs.account_id) "
            "as is_skipped "
            "from jobs where account_id = $1",
            account_id,
        )
        active_rows = [r for r in job_rows if not r["is_skipped"]]
        active_jobs = [(int(r["id"]), r["status"]) for r in active_rows]
        active_ids = {job_id for job_id, _ in active_jobs}
        stage_rows = await pool.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        )
        stages = [
            (int(r["job_id"]), str(r["stage"]), r["changed_at"])
            for r in stage_rows
            if int(r["job_id"]) in active_ids
        ]
        funnel_analytics = compute_funnel_analytics(active_jobs, stages)
        funnel = compute_overview_funnel(
            applied_total=funnel_analytics.applied,
            active_statuses=[status for _, status in active_jobs],
        )
        funnel_period = compute_period_funnel_bars(
            stages=stages, period_start=period_start, period_end=period_end
        )
        aging_jobs = [
            (int(r["id"]), r["status"], r["company"], r["title"], r["overall_score"])
            for r in active_rows
        ]
        aging = compute_stage_aging(aging_jobs, stages)
    except Exception as exc:  # noqa: BLE001 — воронка не критична для остального ответа
        logger.debug("market-overview: воронка/возраст этапов недоступны: %s", exc)

    try:
        dialogs = await count_threads_active_in_period(
            account_id=account_id, period_start=period_start, period_end=period_end, db=pool
        )
        if dialogs > 0:
            # Правка 2026-08-14: Диалоги — базовая корзина воронки (100%), от неё считаются
            # pct всех остальных столбцов (Скрининги/Технички/Финалы/Офферы), а не от суммы всех
            # корзин. Так честнее: «из N заведённых диалогов X дошли до скрининга, Y — до технички».
            # Диалоги идут ПЕРВЫМ столбцом — это база, от которой читается воронка.
            funnel_period = [
                MarketBucket(label=_DIALOGS_LABEL, count=dialogs, pct=100.0),
                *(
                    MarketBucket(label=b.label, count=b.count, pct=_pct(b.count, dialogs))
                    for b in funnel_period
                ),
            ]
        else:
            # Диалогов в периоде нет — столбцы воронки не рисуем (база = 0, pct не определён).
            funnel_period = []
    except Exception as exc:  # noqa: BLE001 — столбик диалогов не критичен для остального ответа
        logger.debug("market-overview: активные диалоги за период недоступны: %s", exc)

    total_scored = sum(band.count for band in search.score_bands)
    gates = GatesOverview(
        total_scored=total_scored,
        self_skipped=search.skipped_total,
        kill_factors=pulse.kill_factors,
        counterfactuals=pulse.gate_counterfactuals,
        breakdown=pulse.gate_breakdown,
    )

    return MarketOverview(
        available=pulse.available,
        days=days,
        from_days=from_days,
        to_days=to_days,
        generated_at=datetime.now(UTC),
        history_start_days=history_start_days,
        money=money,
        market_index=market_index,
        offer_chance=pulse.offer_chance,
        gates=gates,
        funnel=funnel,
        funnel_period=funnel_period,
        dropout_reasons=search.skip_reasons,
        grade_levels=pulse.grade_levels,
        role_niches=pulse.stack_niches,
        stage_aging=aging,
    )


__all__ = [
    "DEFAULT_FROM_DAYS",
    "DEFAULT_OVERVIEW_DAYS",
    "DEFAULT_TO_DAYS",
    "DemandPoint",
    "DemandTrend",
    "FunnelLevel",
    "FunnelLevelSegment",
    "GatesOverview",
    "MarketIndexPoint",
    "MarketOverview",
    "compute_overview_funnel",
    "get_market_overview",
]
