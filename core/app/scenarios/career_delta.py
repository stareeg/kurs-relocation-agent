"""Дельта «Что изменилось» за окно (по умолчанию 30 дней) — экран «Карьера» (Э9.5).

Детерминированное сравнение «было → стало», без LLM. Считает то, для чего есть честный способ
восстановить значение на прошлую дату: балл резюме (история снимков), активные отклики и
конверсия отклик→скрининг (реконструкция по `application_stages`, приём `compute_funnel_at`),
число новых фактов/вех за окно. Медиана старения этапа сознательно не считается — для неё нет
способа восстановить состояние «на дату» (`stage_aging.py` не умеет `as of`), а строить такую
реконструкцию с нуля — за рамками этого захода.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 30


class CareerDelta(BaseModel):
    """«Было → стало» за `window_days`. Поля nullable — метрика без истории не участвует."""

    window_days: int = _WINDOW_DAYS
    resume_score_was: int | None = None
    resume_score_now: int | None = None
    active_applications_was: int | None = None
    active_applications_now: int | None = None
    response_rate_was: float | None = None
    response_rate_now: float | None = None
    new_facts_count: int = 0
    new_milestones_count: int = 0


async def career_delta(
    *,
    account_id: int,
    window_days: int = _WINDOW_DAYS,
    db: Executor | None = None,
) -> CareerDelta | None:
    """`None` — меньше двух точек истории балла резюме (честная пустота, не нули-выдумки)."""
    from core.domains.career.repo import count_facts_since, count_timeline_events_since
    from core.domains.pipeline.analytics import compute_funnel_at, count_active_as_of
    from core.domains.profile.resume_score import load_score_at

    db = db or get_pool()
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    now_score = None
    was_score = None
    try:
        now_score = await load_score_at(cutoff=None, account_id=account_id, db=db)
        was_score = await load_score_at(cutoff=cutoff, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — дельта best-effort, без истории просто None
        logger.debug("career_delta: балл резюме недоступен: %s", exc)

    if now_score is None or was_score is None or now_score.id == was_score.id:
        return None

    job_rows: list = []
    stage_rows: list = []
    try:
        job_rows = await db.fetch(
            "select id, status, created_at from jobs where account_id = $1 "
            "and not exists(select 1 from skipped_vacancies sv where "
            "sv.vacancy_id = jobs.vacancy_id and sv.account_id = jobs.account_id)",
            account_id,
        )
        stage_rows = await db.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("career_delta: воронка недоступна: %s", exc)

    jobs_funnel = [(int(r["id"]), r["status"], r["created_at"]) for r in job_rows]
    jobs_active = [(int(r["id"]), r["status"]) for r in job_rows]
    stages = [(int(r["job_id"]), str(r["stage"]), r["changed_at"]) for r in stage_rows]

    active_now = count_active_as_of(jobs_active, stages, None)
    active_was = count_active_as_of(jobs_active, stages, cutoff)
    funnel_now = compute_funnel_at(jobs_funnel, stages, None)
    funnel_was = compute_funnel_at(jobs_funnel, stages, cutoff)

    new_facts = 0
    new_milestones = 0
    try:
        new_facts = await count_facts_since(cutoff, account_id=account_id, db=db)
        new_milestones = await count_timeline_events_since(cutoff, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001
        logger.debug("career_delta: счётчики фактов/вех недоступны: %s", exc)

    return CareerDelta(
        window_days=window_days,
        resume_score_was=was_score.total,
        resume_score_now=now_score.total,
        active_applications_was=active_was,
        active_applications_now=active_now,
        response_rate_was=funnel_was.response_rate,
        response_rate_now=funnel_now.response_rate,
        new_facts_count=new_facts,
        new_milestones_count=new_milestones,
    )


__all__ = ["CareerDelta", "career_delta"]
