"""Repository провенанса пересчёта скоринга по HR-фактам: накопление по вакансии.

По образцу `core.domains.preparation.debrief`/`core.domains.pipeline.stage_outcome`: своя Pydantic-модель, без зависимости от
api/bot. `facts` — извлечённые HR-факты как jsonb; `facts_hash` — для дедупа (не гнать LLM, если
факты не изменились). Накопительно: исходный JD-скор и каждый пересчёт — отдельной строкой,
`jobs.overall_score` хранит «текущий» (последний hr_confirmed перезаписывает), история живёт здесь.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = (
    "id, vacancy_id, basis, trigger, facts, facts_hash, "
    "overall_score, recommendation, delta, rationale, created_at"
)
# _COLS не несёт account_id — Этап 3 фильтрует WHERE им, но не возвращает наружу (как Job).


class ScoreRevisionRecord(BaseModel):
    """Одна ревизия скоринга: JD-первичная (basis=jd_only) или подтверждённая HR (hr_confirmed)."""

    id: int | None = None
    vacancy_id: str
    basis: str = "jd_only"
    trigger: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)
    facts_hash: str = ""
    overall_score: int = 0
    recommendation: str = ""
    delta: int = 0
    rationale: str = ""
    created_at: datetime | None = None


async def save_score_revision(
    record: ScoreRevisionRecord, *, account_id: int, db: Executor | None = None
) -> ScoreRevisionRecord:
    """Вставить ревизию скоринга. Возвращает с id и created_at."""
    if not record.vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into score_revisions "
        "(vacancy_id, basis, trigger, facts, facts_hash, "
        "overall_score, recommendation, delta, rationale, account_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
        f"returning {_COLS}",
        record.vacancy_id,
        record.basis,
        record.trigger,
        record.facts,
        record.facts_hash,
        record.overall_score,
        record.recommendation,
        record.delta,
        record.rationale,
        account_id,
    )
    assert row is not None
    return ScoreRevisionRecord(**row_to_dict(row))


async def load_score_revisions(
    vacancy_id: str, limit: int = 50, *, account_id: int, db: Executor | None = None
) -> list[ScoreRevisionRecord]:
    """История ревизий по вакансии (свежие первыми)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_COLS} from score_revisions where vacancy_id = $1 and account_id = $3 "
        "order by created_at desc, id desc limit $2",
        vacancy_id,
        capped,
        account_id,
    )
    return [ScoreRevisionRecord(**row_to_dict(r)) for r in rows]


async def count_revisions(vacancy_id: str, *, account_id: int, db: Executor | None = None) -> int:
    """Сколько ревизий по вакансии (есть ли уже baseline-строка)."""
    db = db or get_pool()
    val = await db.fetchval(
        "select count(*) from score_revisions where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    return int(val or 0)


async def latest_hr_fingerprint(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> str | None:
    """facts_hash последней hr_confirmed-ревизии (дедуп: факты не менялись → не пересчитывать)."""
    db = db or get_pool()
    val = await db.fetchval(
        "select facts_hash from score_revisions "
        "where vacancy_id = $1 and basis = 'hr_confirmed' and account_id = $2 "
        "order by created_at desc, id desc limit 1",
        vacancy_id,
        account_id,
    )
    return val if val else None


async def update_latest_hr_fingerprint(
    vacancy_id: str, facts_hash: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Обновить facts_hash последней hr_confirmed без новой строки (скор не сдвинулся)."""
    if not vacancy_id or not facts_hash:
        return False
    db = db or get_pool()
    result = await db.execute(
        "update score_revisions set facts_hash = $2 "
        "where id = ("
        "  select id from score_revisions "
        "  where vacancy_id = $1 and basis = 'hr_confirmed' and account_id = $3 "
        "  order by created_at desc, id desc limit 1"
        ")",
        vacancy_id,
        facts_hash,
        account_id,
    )
    # asyncpg: "UPDATE N"
    return str(result).endswith("1")


__all__ = [
    "ScoreRevisionRecord",
    "save_score_revision",
    "load_score_revisions",
    "count_revisions",
    "latest_hr_fingerprint",
    "update_latest_hr_fingerprint",
]
