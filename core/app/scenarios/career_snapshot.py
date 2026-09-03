"""Снимок «Где я сейчас» для экрана «Карьера» (Э9.2).

Только факты, которые система уже знает — ни одного нового поля ввода. Собирает из
career (режим/трек поиска), profile (статус занятости, рынок поиска, балл резюме) и
opportunities/market (активные отклики, застрявшие). Best-effort по каждому куску —
недоступность одного домена не валит весь снимок (шаблон `vacancy_activity.py`).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from pydantic import BaseModel

from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

T = TypeVar("T")

Employment = Literal["employed", "searching_free", "unknown"]


class CareerSnapshot(BaseModel):
    """Где кандидат сейчас. Только факты, которые система уже знает; ноль ввода."""

    employment: Employment = "unknown"
    search_mode_label: str = ""
    market_scope_label: str = ""
    tracks: list[str] = []
    days_active: int | None = None
    active_applications: int = 0
    stalled: int = 0
    resume_score: int | None = None


async def _or_default(factory: Callable[[], Awaitable[T]], default: T) -> T:
    try:
        return await factory()
    except Exception as exc:  # noqa: BLE001 — снимок best-effort, кусок без PG не роняет экран
        logger.debug("career-snapshot: кусок недоступен: %s", exc)
        return default


def _employment(currently_employed: bool | None) -> Employment:
    if currently_employed is True:
        return "employed"
    if currently_employed is False:
        return "searching_free"
    return "unknown"


async def career_snapshot(*, account_id: int, db: Executor | None = None) -> CareerSnapshot:
    """Собрать снимок «Где я сейчас». Нет данных по куску → честный дефолт, не выдумка."""
    from core.domains.career.search_state import get_current_state
    from core.domains.career.track_state import get_current_tracks
    from core.domains.market.stage_aging import get_stage_aging
    from core.domains.opportunities.jobs import count_active_jobs, get_days_active
    from core.domains.profile.profile import load_candidate_profile_enriched
    from core.domains.profile.resume_score import load_score_at

    search_mode = await _or_default(lambda: get_current_state(account_id=account_id, db=db), None)
    tracks_state = await _or_default(lambda: get_current_tracks(account_id=account_id, db=db), None)
    profile = await _or_default(
        lambda: load_candidate_profile_enriched(account_id=account_id, db=db), None
    )
    days_active = await _or_default(lambda: get_days_active(account_id=account_id, db=db), None)
    active_applications = await _or_default(
        lambda: count_active_jobs(account_id=account_id, db=db), 0
    )
    stage_aging = await _or_default(lambda: get_stage_aging(account_id=account_id, db=db), None)
    score_snapshot = await _or_default(
        lambda: load_score_at(cutoff=None, account_id=account_id, db=db), None
    )

    return CareerSnapshot(
        employment=_employment(profile.currently_employed if profile else None),
        search_mode_label=search_mode.label if search_mode else "",
        market_scope_label=profile.market_scope_label if profile else "",
        tracks=list(tracks_state.labels) if tracks_state else [],
        days_active=days_active,
        active_applications=active_applications,
        stalled=stage_aging.stalled_count if stage_aging else 0,
        resume_score=score_snapshot.total if score_snapshot else None,
    )


__all__ = ["CareerSnapshot", "career_snapshot"]
