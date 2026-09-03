"""Собрать ленту действий по вакансии из нескольких доменов.

Воронка/скор/пропуск — opportunities; этапы и разборы — preparation; оффер — offers.
Подписи строит `opportunities.activity` (коротко, без rationale).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from core.domains.opportunities.activity import (
    ActivityItem,
    debrief_items,
    funnel_items,
    hr_view_item,
    interview_items,
    merge_activity,
    offer_item,
    score_fallback,
    score_items,
    skip_item,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def _or_empty(factory: Callable[[], Awaitable[T]], default: T) -> T:
    try:
        return await factory()
    except Exception as exc:  # noqa: BLE001 — лента best-effort, кусок без PG не роняет вкладку
        logger.debug("vacancy-activity: кусок ленты недоступен: %s", exc)
        return default


async def load_vacancy_activity(vacancy_id: str, *, account_id: int) -> list[ActivityItem]:
    """Все короткие события вакансии, свежие сверху. Нет вакансии / нет PG → []."""
    if not vacancy_id.strip():
        return []

    from core.domains.offers.store import load_offer
    from core.domains.opportunities.jobs import get_job_by_vacancy_id, list_stages
    from core.domains.opportunities.score_revision import load_score_revisions
    from core.domains.opportunities.skipped import get_skipped
    from core.domains.preparation.debrief import load_debrief_history
    from core.domains.preparation.interview_stages import load_stages

    job = await _or_empty(
        lambda: get_job_by_vacancy_id(vacancy_id, account_id=account_id),
        None,
    )

    funnel_rows: list[tuple[int | None, str, str, datetime | None]] = []
    job_id = job.id if job is not None else None
    if job_id is not None:

        async def _funnel() -> list[tuple[int | None, str, str, datetime | None]]:
            stages = await list_stages(job_id, account_id=account_id)
            return [(s.id, s.stage, s.source, s.changed_at) for s in stages]

        funnel_rows = await _or_empty(_funnel, [])

    async def _scores() -> list[tuple[int | None, int, int, str, datetime | None]]:
        recs = await load_score_revisions(vacancy_id, account_id=account_id)
        return [(r.id, r.overall_score, r.delta, r.basis, r.created_at) for r in recs]

    score_rows = await _or_empty(_scores, [])

    skipped = await _or_empty(
        lambda: get_skipped(vacancy_id, account_id=account_id),
        None,
    )

    async def _interviews() -> list[tuple[int | None, str, datetime | None]]:
        stages = await load_stages(vacancy_id, account_id=account_id)
        return [(s.id, s.stage_type, s.created_at) for s in stages]

    interview_rows = await _or_empty(_interviews, [])

    async def _debriefs() -> list[tuple[int | None, str, datetime | None]]:
        recs = await load_debrief_history(vacancy_id, account_id=account_id)
        return [(r.id, r.stage, r.created_at) for r in recs]

    debrief_rows = await _or_empty(_debriefs, [])

    offer = await _or_empty(
        lambda: load_offer(vacancy_id, account_id=account_id),
        None,
    )

    scores = score_items(score_rows)
    if not scores and job is not None:
        scores = score_fallback(job.overall_score, job.scored_at)

    skip = (
        skip_item(
            reason=skipped.skip_reason,
            canonical=skipped.canonical_reason,
            at=skipped.created_at,
            row_id=skipped.id,
        )
        if skipped is not None
        else None
    )

    return merge_activity(
        funnel_items(funnel_rows),
        scores,
        [skip] if skip is not None else [],
        [hr_view_item(job.hr_viewed_at if job is not None else None)],
        interview_items(interview_rows),
        debrief_items(debrief_rows),
        [offer_item(offer.created_at)] if offer is not None else [],
    )


__all__ = ["load_vacancy_activity"]
