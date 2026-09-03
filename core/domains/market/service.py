"""Сценарии домена market — точка входа для роутера/бота.

Отчёты рынка, пульс, сетка, ситуация, калибровка зарплат и скоринга, деньги на рынке.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from core.domains.market.job_stats import JobMarketStats, collect_job_stats
from core.domains.market.market_grid import get_market_grid
from core.domains.market.market_supply import MarketSupplyFacts, get_market_supply_facts
from core.domains.market.pulse import get_market_pulse
from core.domains.market.relevance import CalibrationReport, _furthest, compute_calibration_report
from core.domains.market.salary_benchmark import (
    FxRateScale,
    LiveOfferPoint,
    SalaryBenchmarkReport,
    get_fx_rate_scale,
    get_live_offer_points,
    get_salary_benchmark_report,
)
from core.domains.market.salary_calib_pipeline import (
    analyze_report,
    enqueue_if_salary_post,
    process_pending_queue,
)
from core.domains.market.salary_calib_pipeline import (
    status_text as salary_calib_status_text,
)
from core.domains.market.situation import generate_situation_narrative
from core.domains.opportunities.jobs import SQL_JOB_NOT_SKIPPED
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)


class MoneyOverview(BaseModel):
    """Ответ `GET /api/analytics/money`: две шкалы + планка из резюме + форматы.

    `benchmark` / `supply` / `fx_rates` деградируют независимо (`available=false` без PG или при
    пустой выборке). `salary_min` и `grade_label` — только из `SearchProfile`, без хардкода.
    `fx_rates` — валютные ставки второго трека, без конвертации в рубли.
    """

    benchmark: SalaryBenchmarkReport = Field(default_factory=SalaryBenchmarkReport)
    supply: MarketSupplyFacts = Field(default_factory=MarketSupplyFacts)
    fx_rates: FxRateScale = Field(default_factory=FxRateScale)
    salary_min: int = 0
    grade_label: str = ""
    live_offers: list[LiveOfferPoint] = Field(default_factory=list)


def _grade_label_from_profile(target_grades: list[str]) -> str:
    """Человекочитаемая метка грейда из профиля: «Senior / Lead», пусто если не задано."""
    parts = [g.strip() for g in target_grades if g and str(g).strip()]
    return " / ".join(parts)


async def get_calibration_report(
    *, account_id: int, db: Executor | None = None
) -> CalibrationReport:
    """Калибровка скоринга аккаунта: корзина балла × конверсия в скрининг (срез B).

    Тянет `(overall_score, furthest_stage)` по активным (не в `skipped_vacancies`) вакансиям
    и зовёт чистый `compute_calibration_report`. Нет PG → `available=false`, не исключение.
    """
    try:
        if db is not None:
            pool = db
        else:
            from core.platform.db.pool import get_pool

            pool = get_pool()
    except Exception as exc:  # noqa: BLE001 — нет PG → available=false, не 500
        logger.debug("калибровка скоринга недоступна (нет PG?): %s", exc)
        return CalibrationReport(available=False)

    try:
        job_rows = await pool.fetch(
            "select id, overall_score, status from jobs "
            f"where account_id = $1 and overall_score is not null and {SQL_JOB_NOT_SKIPPED}",
            account_id,
        )
        stage_rows = await pool.fetch(
            "select job_id, stage from application_stages where account_id = $1", account_id
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("калибровка скоринга: выборка недоступна: %s", exc)
        return CalibrationReport(available=False)

    history: dict[int, list[str | None]] = {}
    for r in stage_rows:
        history.setdefault(int(r["job_id"]), []).append(r["stage"])

    pairs: list[tuple[int, int]] = []
    for r in job_rows:
        job_id = int(r["id"])
        statuses: list[str | None] = [r["status"], *history.get(job_id, [])]
        pairs.append((int(r["overall_score"]), _furthest(statuses)))

    return compute_calibration_report(pairs)


async def get_money_overview(*, account_id: int, db: Executor | None = None) -> MoneyOverview:
    """Деньги на рынке для аккаунта: бенчмарк + предложение рынка + планка/грейд из профиля.

    Половинки считаются параллельно и независимо: нет PG → `available=false` у каждой, не 500.
    """
    salary_min = 0
    grade_label = ""
    try:
        from core.domains.profile.profile import load_candidate_profile_enriched
        from core.domains.profile.structured_store import read_resume_data_for_account

        resume_data = await read_resume_data_for_account(account_id, db=db)
        profile = await load_candidate_profile_enriched(
            account_id=account_id, data=resume_data, db=db
        )
        salary_min = int(profile.salary_min or 0)
        grade_label = _grade_label_from_profile(list(profile.target_grades))
    except Exception as exc:  # noqa: BLE001 — нет резюме → планка пустая, блоки всё равно считаем
        logger.debug("money: профиль недоступен: %s", exc)

    async def _benchmark() -> SalaryBenchmarkReport:
        try:
            return await get_salary_benchmark_report(account_id=account_id, db=db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("money: бенчмарк недоступен (нет PG?): %s", exc)
            return SalaryBenchmarkReport(available=False)

    async def _supply() -> MarketSupplyFacts:
        try:
            return await get_market_supply_facts(account_id=account_id, db=db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("money: предложение рынка недоступно (нет PG?): %s", exc)
            return MarketSupplyFacts(available=False)

    async def _live_offers() -> list[LiveOfferPoint]:
        try:
            return await get_live_offer_points(account_id=account_id, db=db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("money: живые офферы недоступны (нет PG?): %s", exc)
            return []

    async def _fx_rates() -> FxRateScale:
        try:
            return await get_fx_rate_scale(account_id=account_id, db=db)
        except Exception as exc:  # noqa: BLE001
            logger.debug("money: валютные ставки недоступны (нет PG?): %s", exc)
            return FxRateScale()

    benchmark, supply, live_offers, fx_rates = await asyncio.gather(
        _benchmark(), _supply(), _live_offers(), _fx_rates()
    )
    return MoneyOverview(
        benchmark=benchmark,
        supply=supply,
        fx_rates=fx_rates,
        salary_min=salary_min,
        grade_label=grade_label,
        live_offers=live_offers,
    )


__all__ = [
    "JobMarketStats",
    "MoneyOverview",
    "analyze_report",
    "collect_job_stats",
    "enqueue_if_salary_post",
    "generate_situation_narrative",
    "get_calibration_report",
    "get_market_grid",
    "get_market_pulse",
    "get_money_overview",
    "process_pending_queue",
    "salary_calib_status_text",
]
