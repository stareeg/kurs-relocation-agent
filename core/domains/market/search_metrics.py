"""KPI поиска работы: воронка конверсии + бэнды скора + активность + офферы.

Вынесено из `api/routers/views.py` (было единственным аналитическим агрегатом, который жил в
роутере, а не в `core/analytics`), чтобы `core.domains.market.situation` могло переиспользовать те же
числа для LLM-сводки без импорта api-слоя из core (обратное направление зависимостей).

Главные числа поиска, а не LLM-cost (тот вторичен, остаётся в `/api/metrics`). Каждый блок
деградирует независимо: нет PG → available=false и нули (фронт честный empty, не 500); упал
отдельный агрегат → остальные всё равно посчитаны.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from core.domains.opportunities.skip_reasons import aggregate_skip_reason_counts
from core.domains.pipeline.analytics import FunnelAnalytics, compute_funnel_at, compute_viewed_stats
from core.domains.pipeline.source_funnel import SourceFunnelReport, compute_source_funnel
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)


class JobScoreBand(BaseModel):
    """Распределение оценённых вакансий по бэндам скора (80+/60-79/<60).

    Имя с префиксом Job — чтобы не путать с `core.domains.market.relevance.ScoreBand` (другой смысл).
    """

    band: str
    count: int


class SkipReasonCount(BaseModel):
    """Топ-причина пропуска вакансии + сколько раз встретилась (skipped_vacancies)."""

    reason: str
    count: int


class SearchMetrics(BaseModel):
    """KPI поиска работы для страницы «Рынок»: воронка + бэнды скора + активность +
    офферы. Главные числа поиска, а не cost (тот вторичен). Нет PG → available=false и нули —
    фронт честно показывает empty, а не 500."""

    available: bool = False
    # Вакансии
    total_jobs: int = 0
    score_bands: list[JobScoreBand] = Field(default_factory=list)
    # Активность
    new_1d: int = 0
    new_7d: int = 0
    new_30d: int = 0
    scored_7d: int = 0
    # Дельты день-ко-дню (сейчас − сутки назад): сколько прибавилось по ступеням за последние сутки.
    delta_applied: int | None = None
    delta_responded: int | None = None
    delta_interviewing: int | None = None
    delta_offers: int | None = None
    # Skip
    skipped_total: int = 0
    skip_reasons: list[SkipReasonCount] = Field(default_factory=list)
    # Офферы
    offers_active: int = 0
    offers_expiring_7d: int = 0
    offers_accepted: int = 0
    offers_declined: int = 0
    offer_accept_rate: float | None = None  # accepted / (accepted + declined)
    # Воронка конверсии (та же, что на «Вакансиях»)
    funnel: FunnelAnalytics = Field(default_factory=FunnelAnalytics)
    # GM-8: конверсия по источнику (hh / getmatch / habr / tg). available — если хоть одна
    # группа набрала min_sample; тонкие группы тоже в slices (rates=None).
    source_funnel: SourceFunnelReport = Field(default_factory=SourceFunnelReport)
    # L-25: снапшот из кэша — когда посчитан и не устарел ли (роутер отдаёт кэш мгновенно).
    generated_at: datetime | None = None
    stale: bool = False


def _window_start(days: int | None) -> datetime | None:
    """Начало окна воронки. `None`/`0`/отрицательное → «всё», без фильтра."""
    if not days or days <= 0:
        return None
    return datetime.now(UTC) - timedelta(days=days)


def _windowed(
    jobs: list[tuple[int, str | None, datetime | None]],
    stages: list[tuple[int, str, datetime | None]],
    window_start: datetime | None,
) -> tuple[list[tuple[int, str | None, datetime | None]], list[tuple[int, str, datetime | None]]]:
    """Оставляет вакансии, созданные в окне, и переходы этапов внутри окна: фильтр сразу
    по `jobs.created_at` и `application_stages.changed_at`, иначе старая вакансия со свежим
    переходом попала бы в короткое окно, а свежая — со старым переходом отдала бы левые ступени.
    """
    if window_start is None:
        return jobs, stages
    kept_ids = {
        job_id
        for job_id, _status, created_at in jobs
        if created_at is not None and created_at >= window_start
    }
    windowed_jobs = [row for row in jobs if row[0] in kept_ids]
    windowed_stages = [
        row
        for row in stages
        if row[0] in kept_ids and row[2] is not None and row[2] >= window_start
    ]
    return windowed_jobs, windowed_stages


async def get_search_metrics(
    *, account_id: int, db: Executor | None = None, days: int | None = None
) -> SearchMetrics:
    """Собрать KPI поиска работы аккаунта из Postgres. Нет PG → available=false, не исключение.

    `days` — окно воронки: 7/30/90 дней или `None`/`0` для «всё». Ограничивает только
    воронку и её производные (доходимость, время между этапами, конверсия по источнику,
    просмотр HR) — бэнды скора, skip-причины и офферы остаются всевременными.
    """
    metrics = SearchMetrics()
    try:
        if db is not None:
            pool = db
        else:
            from core.platform.db.pool import get_pool

            pool = get_pool()
    except Exception as exc:  # noqa: BLE001 — нет PG → available=false, не 500
        logger.debug("search-метрики недоступны (нет PG?): %s", exc)
        return metrics
    metrics.available = True

    # Воронка конверсии (та же выборка, что на «Вакансиях») + дельты день-ко-дню: считаем «сейчас»
    # и «сутки назад» реконструкцией по меткам строк (как в pulse) и вычитаем разницу.
    try:
        job_rows = await pool.fetch(
            "select id, status, created_at, applied_at, hr_viewed_at, source, vacancy_id "
            "from jobs where account_id = $1",
            account_id,
        )
        stage_rows = await pool.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        )

        def _aware(dt: datetime | None) -> datetime | None:
            return dt if dt is None or dt.tzinfo is not None else dt.replace(tzinfo=UTC)

        _STAGE_EPOCH = datetime.min.replace(tzinfo=UTC)

        window_start = _window_start(days)
        fjobs_all = [(r["id"], r["status"], _aware(r["created_at"])) for r in job_rows]
        fstages_raw_all = [
            (int(r["job_id"]), str(r["stage"]), _aware(r["changed_at"])) for r in stage_rows
        ]
        fjobs, fstages_raw = _windowed(fjobs_all, fstages_raw_all, window_start)
        fstages = [(jid, stage, ts or _STAGE_EPOCH) for jid, stage, ts in fstages_raw]
        kept_ids = {jid for jid, _status, _ca in fjobs}
        windowed_job_rows = (
            job_rows if window_start is None else [r for r in job_rows if r["id"] in kept_ids]
        )

        now_f = compute_funnel_at(fjobs, fstages_raw, None)
        ago_f = compute_funnel_at(fjobs, fstages_raw, datetime.now(UTC) - timedelta(days=1))
        # Просмотр резюме HR — сигнал без истории (только текущее значение), поэтому
        # считаем один раз для «сейчас» и мержим в now_f; дельту день-ко-дню не даём (нечем).
        not_viewed, viewed_pending, median_days = compute_viewed_stats(
            [(r["status"], r["applied_at"], r["hr_viewed_at"]) for r in windowed_job_rows]
        )
        metrics.funnel = now_f.model_copy(
            update={
                "applied_not_viewed": not_viewed,
                "applied_viewed_pending": viewed_pending,
                "median_days_to_view": median_days,
            }
        )
        metrics.source_funnel = compute_source_funnel(
            [(r["id"], r["status"], r["source"], r["vacancy_id"]) for r in windowed_job_rows],
            fstages,
        )
        metrics.delta_applied = now_f.applied - ago_f.applied
        metrics.delta_responded = now_f.responded - ago_f.responded
        metrics.delta_interviewing = now_f.interviewing - ago_f.interviewing
        metrics.delta_offers = now_f.offers - ago_f.offers
    except Exception as exc:  # noqa: BLE001
        logger.debug("воронка для метрик недоступна: %s", exc)

    # Вакансии: всего, бэнды скора (80+/60-79/<60), активность за 7/30 дней.
    try:
        row = await pool.fetchrow(
            "select count(*)::bigint total, "
            "count(*) filter (where overall_score >= 80)::bigint hi, "
            "count(*) filter (where overall_score >= 60 and overall_score < 80)::bigint mid, "
            "count(*) filter (where overall_score is not null and overall_score < 60)::bigint lo, "
            "count(*) filter (where created_at >= now() - make_interval(days => 1))::bigint new1, "
            "count(*) filter (where created_at >= now() - make_interval(days => 7))::bigint new7, "
            "count(*) filter (where created_at >= now() - make_interval(days => 30))::bigint new30, "
            "count(*) filter (where scored_at >= now() - make_interval(days => 7))::bigint scored7 "
            "from jobs where account_id = $1",
            account_id,
        )
        if row is not None:
            metrics.total_jobs = int(row["total"])
            metrics.score_bands = [
                JobScoreBand(band="80+", count=int(row["hi"])),
                JobScoreBand(band="60-79", count=int(row["mid"])),
                JobScoreBand(band="<60", count=int(row["lo"])),
            ]
            metrics.new_1d = int(row["new1"])
            metrics.new_7d = int(row["new7"])
            metrics.new_30d = int(row["new30"])
            metrics.scored_7d = int(row["scored7"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("агрегаты вакансий недоступны: %s", exc)

    # Skip: всего + разбивка по канону JS-22.0 (7 причин), не сырой GROUP BY.
    try:
        metrics.skipped_total = int(
            await pool.fetchval(
                "select count(*)::bigint from skipped_vacancies where account_id = $1", account_id
            )
            or 0
        )
        reason_rows = await pool.fetch(
            "select coalesce(nullif(trim(skip_reason), ''), '') reason, "
            "count(*)::bigint cnt from skipped_vacancies where account_id = $1 group by 1",
            account_id,
        )
        aggregated = aggregate_skip_reason_counts(
            [(str(r["reason"]), int(r["cnt"])) for r in reason_rows],
            include_zero=True,
        )
        metrics.skip_reasons = [
            SkipReasonCount(reason=label, count=count) for label, count in aggregated
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug("skip-метрики недоступны: %s", exc)

    # Офферы: активные, истекающие на неделе (deadline в окне now..+7д), accept-rate.
    try:
        orow = await pool.fetchrow(
            "select count(*) filter (where status = 'thinking')::bigint active, "
            "count(*) filter (where status = 'thinking' and deadline is not null "
            "and deadline between now() and now() + make_interval(days => 7))::bigint expiring, "
            "count(*) filter (where status = 'accepted')::bigint accepted, "
            "count(*) filter (where status = 'declined')::bigint declined "
            "from offers where account_id = $1",
            account_id,
        )
        if orow is not None:
            metrics.offers_active = int(orow["active"])
            metrics.offers_expiring_7d = int(orow["expiring"])
            metrics.offers_accepted = int(orow["accepted"])
            metrics.offers_declined = int(orow["declined"])
            decided = metrics.offers_accepted + metrics.offers_declined
            if decided:
                metrics.offer_accept_rate = round(metrics.offers_accepted / decided, 4)
    except Exception as exc:  # noqa: BLE001
        logger.debug("офферные метрики недоступны: %s", exc)

    return metrics


__all__ = [
    "JobScoreBand",
    "SkipReasonCount",
    "SearchMetrics",
    "get_search_metrics",
]
