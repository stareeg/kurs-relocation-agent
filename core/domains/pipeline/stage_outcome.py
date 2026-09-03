"""Repository исходов этапа собеса: структурные факты от рекрутера, накопление по вакансии.

По образцу `core.domains.preparation.debrief`: своя Pydantic-модель, без зависимости от api/bot. `focus_topics`
хранится как jsonb-список (кодек пула json.dumps/loads). Накопительность: каждый исход — отдельная
строка, не перезапись. **Без LLM** — это захват фактов (прошёл/отказ/ждём + фидбек рекрутера + бриф
следующего этапа), не анализ транскрипта (для разбора транскрипта — `core.domains.preparation.debrief`).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = (
    "id, vacancy_id, stage, outcome, recruiter_feedback, next_stage, "
    "next_stage_notes, focus_topics, created_at"
)


class StageOutcomeRecord(BaseModel):
    """Сохранённый исход этапа по вакансии (накопительная история)."""

    id: int | None = None
    vacancy_id: str
    stage: str = "screening"
    outcome: str = "passed"
    recruiter_feedback: str = ""
    next_stage: str = ""
    next_stage_notes: str = ""
    focus_topics: list[str] = Field(default_factory=list)
    created_at: datetime | None = None


async def save_stage_outcome(
    record: StageOutcomeRecord, *, account_id: int, db: Executor | None = None
) -> StageOutcomeRecord:
    """Вставить новый исход этапа. Возвращает с id и created_at."""
    if not record.vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into stage_outcomes "
        "(vacancy_id, stage, outcome, recruiter_feedback, "
        "next_stage, next_stage_notes, focus_topics, account_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8) "
        f"returning {_COLS}",
        record.vacancy_id,
        record.stage,
        record.outcome,
        record.recruiter_feedback,
        record.next_stage,
        record.next_stage_notes,
        record.focus_topics,
        account_id,
    )
    assert row is not None
    return StageOutcomeRecord(**row_to_dict(row))


async def load_stage_outcome_history(
    vacancy_id: str, limit: int = 50, *, account_id: int, db: Executor | None = None
) -> list[StageOutcomeRecord]:
    """История исходов по вакансии (свежие первыми)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_COLS} from stage_outcomes where vacancy_id = $1 and account_id = $3 "
        "order by created_at desc, id desc limit $2",
        vacancy_id,
        capped,
        account_id,
    )
    return [StageOutcomeRecord(**row_to_dict(r)) for r in rows]


__all__ = ["StageOutcomeRecord", "save_stage_outcome", "load_stage_outcome_history"]
