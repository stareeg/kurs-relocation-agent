"""Провенанс пересчёта скоринга по HR-фактам: история ревизий.

Скоринг пересчитывается ПОЛНЫМ АВТО (триггеры в hr-threads/debrief), историю ревизий по
вакансии отдаём здесь для карточки (бейдж «подтверждён HR» + лента 10 → 62 с причиной).
Ручной `POST .../rescore` удалён — не было потребителей; `rescore_from_hr_facts`
остаётся, его зовут только авто-триггеры.

GET деградирует: нет PG → пустая история, карточка не падает.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.schemas import ScoreRevisionHistory, ScoreRevisionOut
from api.security import AccountContext, require_account_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/score-revision", tags=["score-revision"])


def _out(rec) -> ScoreRevisionOut:
    return ScoreRevisionOut(
        vacancy_id=rec.vacancy_id,
        basis=rec.basis,  # type: ignore[arg-type]
        trigger=rec.trigger,
        facts=rec.facts,
        overall_score=rec.overall_score,
        recommendation=rec.recommendation,
        delta=rec.delta,
        rationale=rec.rationale,
        id=rec.id,
        created_at=rec.created_at,
    )


@router.get("/{vacancy_id}", response_model=ScoreRevisionHistory)
async def history(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> ScoreRevisionHistory:
    """История ревизий скоринга по вакансии (свежие первыми) + текущий basis. Нет PG → пусто."""
    basis = "jd_only"
    try:
        from core.domains.opportunities.jobs import get_job_by_vacancy_id
        from core.domains.opportunities.score_revision import load_score_revisions

        records = await load_score_revisions(vacancy_id, limit=50, account_id=account.account_id)
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account.account_id)
        if job is not None:
            basis = job.score_basis
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая история
        logger.debug("score-revision: история из Postgres недоступна: %s", exc)
        return ScoreRevisionHistory(vacancy_id=vacancy_id, items=[])
    return ScoreRevisionHistory(
        vacancy_id=vacancy_id, score_basis=basis, items=[_out(r) for r in records]
    )
