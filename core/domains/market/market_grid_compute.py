"""Расчёт метрик сетки «Рынок» (окно 30д + headline KPI из pulse).

Чистые функции над строками jobs / application_stages / skipped_vacancies / hr_messages.
`market_grid.build_market_grid` собирает ячейки в фиксированном порядке GRID_SPEC.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median

from core.domains.opportunities.jobs import (
    SOURCE_HR_THREAD_STUB,
    SOURCE_TELEGRAM_CHANNEL,
    resolve_job_source_group,
)
from core.domains.opportunities.skip_reasons import SELF_SKIP_REASONS, canonical_skip_reason
from core.kernel.schemas.funnel import FunnelStatus, funnel_stage_number, resolve_funnel_status

GRID_WINDOW_DAYS = 30


@dataclass(frozen=True)
class GridJobRow:
    id: int
    status: str | None
    created_at: datetime | None
    scored_at: datetime | None
    applied_at: str | None
    overall_score: int | None
    source: str | None
    vacancy_id: str | None
    # Пропуск ортогонален status: явный отказ калибровать под эту вакансию.
    is_skipped: bool = False


_SORT_EPOCH = datetime.min.replace(tzinfo=UTC)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


def _sort_ts(dt: datetime | None) -> datetime:
    aware = _aware(dt)
    return aware if aware is not None else _SORT_EPOCH


def _pct1(numer: int, denom: int) -> float | None:
    if denom <= 0:
        return None
    return round(numer / denom * 1000) / 10


def _first_stage_map(
    stages: list[tuple[int, str, datetime | None]],
) -> dict[int, dict[int, datetime]]:
    out: dict[int, dict[int, datetime]] = {}
    for job_id, stage, changed_at in stages:
        if changed_at is None:
            continue
        n = funnel_stage_number(stage)
        if not isinstance(n, int) or n <= 0:
            continue
        slots = out.setdefault(job_id, {})
        ts = _aware(changed_at)
        if ts is not None and (n not in slots or ts < slots[n]):
            slots[n] = ts
    return out


def _parse_applied_at(raw: str | None) -> datetime | None:
    if not raw or len(raw) < 10:
        return None
    try:
        from datetime import date

        d = date.fromisoformat(raw[:10])
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    except ValueError:
        return None


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(median(values), 1)


def _in_window(ts: datetime | None, cutoff: datetime) -> bool:
    return ts is not None and ts >= cutoff


def compute_market_grid_values(
    *,
    jobs: list[GridJobRow],
    stages: list[tuple[int, str, datetime | None]],
    skipped_rows: list[tuple[str, datetime | None]],
    hr_first_inbound: dict[str, datetime],
    kpis: dict[str, tuple[float, float | None]],
    offer_chance_score: float,
    offer_chance_delta: float | None,
    resume_quality: int | None,
    resume_quality_delta: float | None,
    now: datetime | None = None,
) -> dict[str, tuple[float | int | str | None, float | None, str | None]]:
    """Словарь key → (value, delta, empty_reason)."""
    now = _aware(now) or datetime.now(UTC)
    cutoff = now - timedelta(days=GRID_WINDOW_DAYS)
    first_at = _first_stage_map(stages)
    job_by_id = {j.id: j for j in jobs}
    # Активные = не в skipped_vacancies. Пропуск - не этап воронки, а явный отказ.
    active = [j for j in jobs if not j.is_skipped]

    scored_30d = sum(1 for j in active if _in_window(_aware(j.scored_at), cutoff))
    scored_scores = [
        int(j.overall_score)
        for j in active
        if _in_window(_aware(j.scored_at), cutoff) and j.overall_score is not None
    ]
    avg_score_30d = round(sum(scored_scores) / len(scored_scores), 1) if scored_scores else None
    score_60_plus_30d = sum(1 for s in scored_scores if s >= 60)

    applied_job_ids: set[int] = set()
    screening_job_ids: set[int] = set()
    tech_job_ids: set[int] = set()
    final_job_ids: set[int] = set()
    offer_job_ids: set[int] = set()
    hr_outreach_job_ids: set[int] = set()

    active_ids = {j.id for j in active}
    for job_id, slots in first_at.items():
        if job_id not in active_ids:
            continue
        if 2 in slots and _in_window(slots[2], cutoff):
            applied_job_ids.add(job_id)
        if 3 in slots and _in_window(slots[3], cutoff):
            screening_job_ids.add(job_id)
        if 4 in slots and _in_window(slots[4], cutoff):
            tech_job_ids.add(job_id)
        if 5 in slots and _in_window(slots[5], cutoff):
            final_job_ids.add(job_id)
        if 6 in slots and _in_window(slots[6], cutoff):
            offer_job_ids.add(job_id)

    for job in active:
        vid = (job.vacancy_id or "").strip()
        hr_at = hr_first_inbound.get(vid)
        if hr_at is None or not _in_window(_aware(hr_at), cutoff):
            continue
        applied_ts = first_at.get(job.id, {}).get(2)
        if applied_ts is None or hr_at < applied_ts:
            hr_outreach_job_ids.add(job.id)

    applied_30d = len(applied_job_ids)
    screenings_30d = len(screening_job_ids)
    tech_30d = len(tech_job_ids)
    final_30d = len(final_job_ids)
    screening_denom = len(applied_job_ids | hr_outreach_job_ids)
    screening_pct_30d = _pct1(screenings_30d, screening_denom)
    tech_pct_30d = _pct1(tech_30d, screenings_30d)

    hr_responses_30d = len(
        {
            job_id
            for job_id in screening_job_ids
            if job_id in job_by_id
            and (
                (job_by_id[job_id].vacancy_id or "") in hr_first_inbound
                or resolve_job_source_group(job_by_id[job_id].source, job_by_id[job_id].vacancy_id)
                == "tg"
            )
        }
    )
    if hr_responses_30d == 0 and screenings_30d > 0:
        hr_responses_30d = screenings_30d

    active_pipeline = sum(
        1
        for j in active
        if resolve_funnel_status(j.status)
        in {FunnelStatus.SCREENING, FunnelStatus.TECH, FunnelStatus.FINAL, FunnelStatus.OFFER}
    )
    tech_ever = len({jid for jid, slots in first_at.items() if jid in active_ids and 4 in slots})
    offers_ever = len({jid for jid, slots in first_at.items() if jid in active_ids and 6 in slots})
    offers_total = offers_ever
    offer_pct = _pct1(offers_ever, tech_ever)

    minutes_to_apply: list[float] = []
    hours_to_screening: list[float] = []
    hours_to_tech: list[float] = []
    hours_to_offer: list[float] = []

    for job_id, slots in first_at.items():
        job = job_by_id.get(job_id)
        if job is None or job.is_skipped:
            continue
        viewed = slots.get(1) or _aware(job.scored_at) or _aware(job.created_at)
        applied = slots.get(2) or _parse_applied_at(job.applied_at)
        screening = slots.get(3)
        tech = slots.get(4)
        offer = slots.get(6)
        vid = (job.vacancy_id or "").strip()
        hr_start = hr_first_inbound.get(vid)

        if applied and viewed and _in_window(applied, cutoff):
            delta_min = (applied - viewed).total_seconds() / 60.0
            if delta_min >= 0:
                minutes_to_apply.append(delta_min)

        if screening and _in_window(screening, cutoff):
            start = applied or hr_start
            if start and screening >= start:
                hours_to_screening.append((screening - start).total_seconds() / 3600.0)

        if tech and screening and _in_window(tech, cutoff) and tech >= screening:
            hours_to_tech.append((tech - screening).total_seconds() / 3600.0)

        if offer and tech and _in_window(offer, cutoff) and offer >= tech:
            hours_to_offer.append((offer - tech).total_seconds() / 3600.0)

    tg_job_ids: set[int] = set()
    for job in active:
        vid = (job.vacancy_id or "").strip()
        src = (job.source or "").strip()
        group = resolve_job_source_group(src, vid)
        has_hr = vid in hr_first_inbound
        platform_apply = bool(job.applied_at) or 2 in first_at.get(job.id, {})
        if (
            has_hr
            and not platform_apply
            or group == "tg"
            and not platform_apply
            or src in {SOURCE_HR_THREAD_STUB, SOURCE_TELEGRAM_CHANNEL}
        ):
            tg_job_ids.add(job.id)
    tg_vacancies = len(tg_job_ids)

    skip_counts_30d: dict[str, int] = {label: 0 for label in SELF_SKIP_REASONS}
    skipped_total_30d = 0
    for reason, scored_at in skipped_rows:
        ts = _aware(scored_at)
        if not _in_window(ts, cutoff):
            continue
        skipped_total_30d += 1
        canon = canonical_skip_reason(reason)
        skip_counts_30d[canon] = skip_counts_30d.get(canon, 0) + 1

    def _kpi(
        key: str, *, empty_hint: str | None = None
    ) -> tuple[float | int | None, float | None, str | None]:
        if key not in kpis:
            return None, None, empty_hint
        val, delta = kpis[key]
        return val, delta, None

    values: dict[str, tuple[float | int | str | None, float | None, str | None]] = {
        "scored_30d": (scored_30d, None, None),
        "applied_30d": (applied_30d, None, None),
        "hr_responses_30d": (
            hr_responses_30d,
            None,
            None if hr_responses_30d else "нет ответов HR",
        ),
        "avg_score_30d": (
            avg_score_30d,
            None,
            None if avg_score_30d is not None else "нет скоринга за 30д",
        ),
        "score_60_plus_30d": (score_60_plus_30d, None, None),
        "offer_chance": (offer_chance_score, offer_chance_delta, None),
        "active_pipeline": (active_pipeline, None, None),
        "screenings_30d": (screenings_30d, None, None),
        "screening_pct_30d": (
            screening_pct_30d,
            None,
            None if screening_pct_30d is not None else "нет откликов/контактов",
        ),
        "tech_30d": (tech_30d, None, None),
        "tech_pct_30d": (
            tech_pct_30d,
            None,
            None if tech_pct_30d is not None else "нет скринингов",
        ),
        "final_30d": (final_30d, None, None),
        "offers_total": (offers_total, None, None),
        "offer_pct": (offer_pct, None, None if offer_pct is not None else "нет техничек"),
        "time_to_apply": (
            _median_or_none(minutes_to_apply),
            None,
            None if minutes_to_apply else "нет откликов за 30д",
        ),
        "time_to_screening": (
            _median_or_none(hours_to_screening),
            None,
            None if hours_to_screening else "нет переходов в скрининг",
        ),
        "time_to_tech": (
            _median_or_none(hours_to_tech),
            None,
            None if hours_to_tech else "нет переходов в техничку",
        ),
        "time_to_offer": (
            _median_or_none(hours_to_offer),
            None,
            None if hours_to_offer else "нет офферов за 30д",
        ),
        "recommended_vacancies": _kpi(
            "recommended_vacancies",
            empty_hint="снимет расширение с профиля hh",
        ),
        "impressions": _kpi("impressions", empty_hint="снимет расширение с профиля hh"),
        "views": _kpi("views", empty_hint="снимет расширение с профиля hh"),
        "getmatch_views": _kpi(
            "getmatch_views",
            empty_hint="снимет расширение getmatch /profile/statistics",
        ),
        "resume_quality": (
            resume_quality,
            resume_quality_delta,
            None if resume_quality is not None else "нет снимков балла резюме",
        ),
        "tg_vacancies": (tg_vacancies, None, None),
        "skipped_30d": (skipped_total_30d, None, None),
        "skip_low_salary": (skip_counts_30d.get("Низкая зарплата", 0), None, None),
        "skip_low_grade": (skip_counts_30d.get("Низкий грейд", 0), None, None),
        "skip_wrong_stack_domain": (skip_counts_30d.get("Не тот стек/домен", 0), None, None),
        "skip_wrong_format": (skip_counts_30d.get("Не тот формат", 0), None, None),
        "skip_role_kind": (skip_counts_30d.get("Не та роль (IC vs рук)", 0), None, None),
        "skip_bad_company": (skip_counts_30d.get("Избегать компанию", 0), None, None),
    }
    return values


async def load_market_grid_inputs(
    *, account_id: int, db
) -> tuple[list[GridJobRow], list, list, dict[str, datetime]]:
    job_rows, stage_rows, skipped_rows, hr_rows = await asyncio.gather(
        db.fetch(
            "select id, status, created_at, scored_at, applied_at, overall_score, source, vacancy_id, "
            "exists(select 1 from skipped_vacancies sv where sv.vacancy_id = jobs.vacancy_id "
            "and sv.account_id = jobs.account_id) "
            "as is_skipped "
            "from jobs where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select coalesce(nullif(trim(skip_reason), ''), '') reason, scored_at "
            "from skipped_vacancies where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select ht.vacancy_id, min(m.sent_at) as first_at "
            "from hr_threads ht "
            "join hr_messages m on m.thread_id = ht.id "
            "where m.direction = 'in' and ht.channel = 'telegram' and ht.account_id = $1 "
            "group by ht.vacancy_id",
            account_id,
        ),
    )

    jobs = [
        GridJobRow(
            id=int(r["id"]),
            status=r["status"],
            created_at=_aware(r["created_at"]),
            scored_at=_aware(r["scored_at"]),
            applied_at=r["applied_at"],
            overall_score=int(r["overall_score"]) if r["overall_score"] is not None else None,
            source=r["source"],
            vacancy_id=r["vacancy_id"],
            is_skipped=bool(r["is_skipped"]),
        )
        for r in job_rows
    ]
    stages = [(int(r["job_id"]), str(r["stage"]), _sort_ts(r["changed_at"])) for r in stage_rows]
    skipped = [(str(r["reason"]), _aware(r["scored_at"])) for r in skipped_rows]
    hr_first: dict[str, datetime] = {}
    for r in hr_rows:
        if r["first_at"] is None:
            continue
        dt = _aware(r["first_at"])
        if dt is not None:
            hr_first[str(r["vacancy_id"])] = dt
    return jobs, stages, skipped, hr_first


__all__ = [
    "GRID_WINDOW_DAYS",
    "GridJobRow",
    "compute_market_grid_values",
    "load_market_grid_inputs",
]
