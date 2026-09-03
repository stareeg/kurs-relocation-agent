"""Разделяющая сила осей `score_breakdown` по решениям владельца (Этап 7 §7.2-7.3, read-only).

НЕ путать с `core.domains.market.relevance.CalibrationReport` («Срез B» — балл-бэнд × конверсия
в HR-ответ, предиктивная валидность модели). Здесь другой срез: какая из ШЕСТИ ОСЕЙ скоринга
(salary/work_format/grade_match/role_content/management/company) вообще отличает вакансии, на
которые владелец откликнулся, от тех, что он просто пролистал (plans/scoring_precision_2026_08_17.md
§1.6/§1.9 — самый ценный неиспользуемый сигнал в базе). Чистая агрегация по уже посчитанным
`jobs`/`skipped_vacancies`, БЕЗ LLM и БЕЗ записи: `overall_score`/`score_breakdown` не трогаются,
веса рубрики не двигаются автоматически — только отчёт + опциональная советующая подсказка
(`suggest_weight_adjustment`). Применение — не отсюда: см. `rescore.simulate_weight_override`
(Этап 7 §7.3) — тоже ничего не пишет, только прогоняет гипотетическую рубрику по уже
сохранённому `score` jsonb.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.domains.opportunities.jobs import Job, list_jobs
from core.domains.opportunities.skip_reasons import aggregate_skip_reason_counts
from core.kernel.schemas.funnel import has_responded_status
from core.platform.db.pool import Executor, get_pool

# Эффективно «без лимита» для масштаба одного аккаунта (сотни-тысячи вакансий, не десятки тысяч,
# CLAUDE.md) — переиспользуем `list_jobs` (даёт `skipped` через JOIN и учитывает hr_confirmed
# рескор) вместо новой SQL-выборки; жёсткий limit у неё обязателен, поэтому явно завышен.
_REPORT_JOB_LIMIT = 20_000

_AXES: tuple[str, ...] = (
    "salary",
    "work_format",
    "grade_match",
    "role_content",
    "management",
    "company",
)

_MIN_BUCKET_SAMPLE = 10
_HIGH_SCORE_THRESHOLD = 80
_LOW_SCORE_THRESHOLD = 55
_DISCREPANCY_LIMIT = 20
# Делта (в баллах оси), ниже которой инверсия считается значимой, а не шумом на малой выборке.
_INVERSION_THRESHOLD = -0.5


def _is_scored(job: Job) -> bool:
    """Реально оценённая вакансия, не stub (D16): у stub'ов `score = {}` по умолчанию."""
    return bool((job.score or {}).get("score_breakdown"))


def _axis_points(job: Job, axis: str) -> float | None:
    value = (job.score or {}).get("score_breakdown", {}).get(axis)
    return float(value) if isinstance(value, int | float) else None


def _bucket_avg(jobs: list[Job], axis: str) -> tuple[float | None, int]:
    values = [v for job in jobs if (v := _axis_points(job, axis)) is not None]
    if not values:
        return None, 0
    return round(sum(values) / len(values), 1), len(values)


class AxisAlignment(BaseModel):
    """Разделяющая сила одной оси score_breakdown (Этап 7 §7.2 — таблица плана §1.6)."""

    axis: str
    avg_responded: float | None = None
    avg_not_responded: float | None = None
    delta: float | None = None
    inverted: bool = False
    n_responded: int = 0
    n_not_responded: int = 0


class AlignmentDiscrepancy(BaseModel):
    """Одна вакансия, где решение владельца разошлось со скором (план §1.9)."""

    job_id: int
    vacancy_id: str | None = None
    title: str | None = None
    company: str | None = None
    url: str | None = None
    overall_score: int
    status: str | None = None
    gate_triggered: str | None = None


class WeightSuggestion(BaseModel):
    """Советующая правка веса — НЕ применяется автоматически (Этап 7 §7.3)."""

    axis: str
    current_weight: int
    suggested_weight: int
    delta: float
    reason: str


class AxisAlignmentReport(BaseModel):
    """Read-only отчёт: ничего не пишет, не двигает веса. `suggestion` — только совет."""

    insufficient_data: bool = False
    n_responded: int = 0
    n_not_responded: int = 0
    n_skipped: int = 0
    axes: list[AxisAlignment] = Field(default_factory=list)
    high_score_no_response: list[AlignmentDiscrepancy] = Field(default_factory=list)
    low_score_responded: list[AlignmentDiscrepancy] = Field(default_factory=list)
    skip_reason_counts: list[tuple[str, int]] = Field(default_factory=list)
    suggestion: WeightSuggestion | None = None


def _to_discrepancy(job: Job) -> AlignmentDiscrepancy:
    return AlignmentDiscrepancy(
        job_id=job.id or 0,
        vacancy_id=job.vacancy_id,
        title=job.title,
        company=job.company,
        url=job.url,
        overall_score=job.overall_score or 0,
        status=job.status,
        gate_triggered=(job.score or {}).get("gate_triggered"),
    )


def build_axis_alignment_report_from_rows(
    jobs: list[Job], skip_reasons_raw: list[str]
) -> AxisAlignmentReport:
    """Чистая агрегация — без DB, для юнит-тестов. `jobs` — как из `list_jobs` (со `skipped`)."""
    scored = [j for j in jobs if _is_scored(j)]
    responded = [j for j in scored if has_responded_status(j.status)]
    # «Молчание» — НЕ включает явные пропуски: у пропуска уже есть причина, это не то же самое,
    # что вакансия, на которую владелец просто ни разу не отреагировал.
    silent = [j for j in scored if not has_responded_status(j.status) and not j.skipped]

    insufficient_data = len(responded) < _MIN_BUCKET_SAMPLE or len(silent) < _MIN_BUCKET_SAMPLE
    axes: list[AxisAlignment] = []
    if not insufficient_data:
        for axis in _AXES:
            avg_r, n_r = _bucket_avg(responded, axis)
            avg_nr, n_nr = _bucket_avg(silent, axis)
            delta = round(avg_r - avg_nr, 1) if avg_r is not None and avg_nr is not None else None
            axes.append(
                AxisAlignment(
                    axis=axis,
                    avg_responded=avg_r,
                    avg_not_responded=avg_nr,
                    delta=delta,
                    inverted=bool(delta is not None and delta < 0),
                    n_responded=n_r,
                    n_not_responded=n_nr,
                )
            )

    high_score_no_response = sorted(
        (j for j in silent if (j.overall_score or 0) >= _HIGH_SCORE_THRESHOLD),
        key=lambda j: j.overall_score or 0,
        reverse=True,
    )[:_DISCREPANCY_LIMIT]
    low_score_responded = sorted(
        (j for j in responded if (j.overall_score or 0) < _LOW_SCORE_THRESHOLD),
        key=lambda j: j.overall_score or 0,
    )[:_DISCREPANCY_LIMIT]

    skip_counts = aggregate_skip_reason_counts([(reason, 1) for reason in skip_reasons_raw])

    return AxisAlignmentReport(
        insufficient_data=insufficient_data,
        n_responded=len(responded),
        n_not_responded=len(silent),
        n_skipped=len(skip_reasons_raw),
        axes=axes,
        high_score_no_response=[_to_discrepancy(j) for j in high_score_no_response],
        low_score_responded=[_to_discrepancy(j) for j in low_score_responded],
        skip_reason_counts=skip_counts,
    )


def suggest_weight_adjustment(
    report: AxisAlignmentReport, weights: dict[str, int]
) -> WeightSuggestion | None:
    """Худшая по разделяющей силе ось, если инверсия значима — иначе None (Этап 7 §7.3).

    Не применяет ничего: только текст + числа для UI-подсказки. `overall_score` рубрики этим
    вызовом не меняется — веса не персистятся нигде (Этап 8 D14 выпиливает саму идею хранить
    ручной оверрайд весов, а не вводит новый).
    """
    if report.insufficient_data or not report.axes:
        return None
    worst = min(report.axes, key=lambda a: a.delta if a.delta is not None else 0.0)
    if worst.delta is None or worst.delta > _INVERSION_THRESHOLD:
        return None
    current = int(weights.get(worst.axis, 0))
    if current <= 0:
        return None
    step = max(3, round(current * 0.25))
    suggested = max(0, current - step)
    return WeightSuggestion(
        axis=worst.axis,
        current_weight=current,
        suggested_weight=suggested,
        delta=worst.delta,
        reason=(
            f"Ось «{worst.axis}» не разделяет ваши решения: в среднем {worst.avg_responded} "
            f"балла у вакансий, на которые вы откликнулись, против {worst.avg_not_responded} "
            "у тех, что просто пролистали."
        ),
    )


async def build_axis_alignment_report(
    account_id: int, *, db: Executor | None = None
) -> AxisAlignmentReport:
    """Отчёт + советующая подсказка по весам для аккаунта. Ничего не пишет."""
    from core.domains.opportunities.rescore import resolve_current_weights

    executor = db or get_pool()
    jobs = await list_jobs(limit=_REPORT_JOB_LIMIT, account_id=account_id, db=executor)
    skip_rows = await executor.fetch(
        "select skip_reason from skipped_vacancies where account_id = $1", account_id
    )
    report = build_axis_alignment_report_from_rows(
        jobs, [r["skip_reason"] for r in skip_rows if r["skip_reason"]]
    )
    try:
        weights = await resolve_current_weights(account_id)
        report.suggestion = suggest_weight_adjustment(report, weights)
    except Exception:  # noqa: BLE001 — подсказка best-effort, отчёт важнее
        pass
    return report


__all__ = [
    "AlignmentDiscrepancy",
    "AxisAlignment",
    "AxisAlignmentReport",
    "WeightSuggestion",
    "build_axis_alignment_report",
    "build_axis_alignment_report_from_rows",
    "suggest_weight_adjustment",
]
