"""Repository истории скора резюме: снимок при полном refresh.

Компоненты: structure / market_coverage (nullable) / writing / role_fit.
`market_coverage is None` — нет словаря/корпуса, в total не входил.
Идемпотентность — подряд идущий снимок с теми же числами + hash не дублируем.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.domains.profile.gap import ResumeScoreBreakdown, ScoreFixItem
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = (
    "id, total, structure, market_coverage, writing, role_fit, "
    "resume_hash, corpus_fp, writing_ready, role_fit_ready, audit_json, created_at"
)
# account_id читаем отдельно от публичной формы снимка (ResumeScoreSnapshot его не несёт —
# наружу это внутренний фильтр, не поле ответа) — фильтруем им WHERE, не проецируем в _COLS.


class ResumeScoreSnapshot(BaseModel):
    """Один снимок балла резюме во времени (доступные компоненты)."""

    id: int | None = None
    total: int
    structure: int
    market_coverage: int | None = None
    writing: int
    role_fit: int
    resume_hash: str = ""
    corpus_fp: str = ""
    writing_ready: bool = False
    role_fit_ready: bool = False
    audit_json: dict | None = None
    created_at: datetime | None = None


def audit_fixes_from_snapshot(snapshot: ResumeScoreSnapshot | None) -> list[ScoreFixItem]:
    if snapshot is None or not snapshot.audit_json:
        return []
    raw = snapshot.audit_json.get("fixes")
    if not isinstance(raw, list):
        return []
    out: list[ScoreFixItem] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(ScoreFixItem.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
    return out


def audit_json_from_score(score: ResumeScoreBreakdown) -> dict | None:
    if not score.score_fixes:
        return None
    return {"fixes": [f.model_dump(mode="json") for f in score.score_fixes]}


async def save_score_snapshot(
    score: ResumeScoreBreakdown,
    *,
    account_id: int,
    resume_hash: str = "",
    corpus_fp: str = "",
    writing_ready: bool = True,
    role_fit_ready: bool = True,
    db: Executor | None = None,
) -> ResumeScoreSnapshot | None:
    """Вставить снимок аккаунта запроса, если отличается от его последнего (де-дуп повторных
    сейвов) — сравнение и запись строго в пределах `account_id` (M1, было: последняя строка на
    всю систему, §3.1 п.4)."""
    db = db or get_pool()
    last = await db.fetchrow(
        f"select {_COLS} from resume_score_history where account_id = $1 "
        "order by created_at desc, id desc limit 1",
        account_id,
    )
    if last is not None and (
        last["total"] == score.total
        and last["structure"] == score.structure
        and last["market_coverage"] == score.market_coverage
        and last["writing"] == score.writing
        and last["role_fit"] == score.role_fit
        and (last["resume_hash"] or "") == (resume_hash or "")
        and (last["corpus_fp"] or "") == (corpus_fp or "")
    ):
        return None

    row = await db.fetchrow(
        "insert into resume_score_history "
        "(account_id, total, structure, market_coverage, writing, role_fit, "
        " resume_hash, corpus_fp, writing_ready, role_fit_ready, audit_json) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb) returning " + _COLS,
        account_id,
        score.total,
        score.structure,
        score.market_coverage,
        score.writing,
        score.role_fit,
        resume_hash or "",
        corpus_fp or "",
        writing_ready,
        role_fit_ready,
        audit_json_from_score(score),
    )
    assert row is not None
    return ResumeScoreSnapshot(**row_to_dict(row))


async def load_score_history(
    limit: int = 30, *, account_id: int, db: Executor | None = None
) -> list[ResumeScoreSnapshot]:
    """История снимков аккаунта запроса, от старых к новым (для тренд-линии)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_COLS} from resume_score_history where account_id = $1 "
        "order by created_at desc, id desc limit $2",
        account_id,
        capped,
    )
    snapshots = [ResumeScoreSnapshot(**row_to_dict(r)) for r in rows]
    return list(reversed(snapshots))


async def load_score_at(
    cutoff: datetime | None = None, *, account_id: int, db: Executor | None = None
) -> ResumeScoreSnapshot | None:
    """Последний снимок аккаунта запроса на момент `cutoff` (None = самый свежий)."""
    db = db or get_pool()
    if cutoff is None:
        row = await db.fetchrow(
            f"select {_COLS} from resume_score_history where account_id = $1 "
            "order by created_at desc, id desc limit 1",
            account_id,
        )
    else:
        row = await db.fetchrow(
            f"select {_COLS} from resume_score_history "
            "where account_id = $1 and (created_at is null or created_at <= $2) "
            "order by created_at desc, id desc limit 1",
            account_id,
            cutoff,
        )
    if row is None:
        return None
    return ResumeScoreSnapshot(**row_to_dict(row))


__all__ = [
    "ResumeScoreSnapshot",
    "audit_fixes_from_snapshot",
    "audit_json_from_score",
    "load_score_at",
    "load_score_history",
    "save_score_snapshot",
]
