"""Repository разборов собеса: персист и история по вакансии.

По образцу `core.domains.preparation.prep`: своя Pydantic-модель, без зависимости от api/bot. `analysis` хранится
как jsonb (весь `DebriefAnalysis` в режиме json — datetime → ISO-строка, иначе json.dumps в кодеке
пула падает). Денормализованные signal/impression/summary дублируют поля analysis ради дешёвого
списка истории без разбора jsonb. Накопительность: каждый разбор — отдельная строка, не перезапись.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.domains.preparation.events import publish_interview_debriefed
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = (
    "id, vacancy_id, stage, transcript, signal, impression, summary, analysis, "
    "interview_stage_id, resolution, resolved_at, resolved_note, created_at"
)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetime → UTC-aware (timestamptz). PG-времена уже aware, ручные — могут быть naive."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class DebriefRecord(BaseModel):
    """Сохранённый разбор собеса по вакансии (накопительная история)."""

    id: int | None = None
    vacancy_id: str
    stage: str = "tech"
    transcript: str = ""
    signal: str = "unknown"
    impression: int = 5
    summary: str = ""
    analysis: dict[str, Any] = Field(default_factory=dict)
    # UX2-9: конкретный экземпляр этапа цепочки (interview_stages.id), к которому относится этот
    # разбор — None, если владелец не привязал (или цепочка пуста/этап неизвестен).
    interview_stage_id: int | None = None
    # DBR-5: жизненный цикл сигнала — pending (сразу после анализа) → advanced/rejected (по факту
    # последующей переписки с HR, см. core.interview.debrief_resolution).
    resolution: str = "pending"
    resolved_at: datetime | None = None
    resolved_note: str = ""
    created_at: datetime | None = None


async def save_debrief(
    record: DebriefRecord, *, account_id: int, db: Executor | None = None
) -> DebriefRecord:
    """Вставить новый разбор. Возвращает с id и created_at."""
    if not record.vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into interview_debriefs "
        "(account_id, vacancy_id, stage, transcript, signal, impression, summary, analysis, "
        "interview_stage_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        f"returning {_COLS}",
        account_id,
        record.vacancy_id,
        record.stage,
        record.transcript,
        record.signal,
        record.impression,
        record.summary,
        record.analysis,
        record.interview_stage_id,
    )
    assert row is not None
    saved = DebriefRecord(**row_to_dict(row))

    # A-11: разбор сохранён — единственная точка записи, поэтому событие публикуем здесь.
    publish_interview_debriefed(
        vacancy_id=saved.vacancy_id,
        account_id=account_id,
        stage=saved.stage,
        signal=saved.signal,
        debrief_id=saved.id,
    )
    return saved


async def load_debrief_history(
    vacancy_id: str, limit: int = 20, *, account_id: int, db: Executor | None = None
) -> list[DebriefRecord]:
    """История разборов по вакансии (свежие первыми)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_COLS} from interview_debriefs where vacancy_id = $1 and account_id = $2 "
        "order by created_at desc, id desc limit $3",
        vacancy_id,
        account_id,
        capped,
    )
    return [DebriefRecord(**row_to_dict(r)) for r in rows]


async def get_debrief(
    debrief_id: int, *, account_id: int, db: Executor | None = None
) -> DebriefRecord | None:
    """Один разбор по id (извлечение фактов после `InterviewDebriefed`)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLS} from interview_debriefs where id = $1 and account_id = $2",
        debrief_id,
        account_id,
    )
    return DebriefRecord(**row_to_dict(row)) if row else None


async def load_latest_pending_debrief(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> DebriefRecord | None:
    """Самый свежий разбор вакансии, ещё не подтверждённый/опровергнутый перепиской.

    Опирается на частичный индекс `interview_debriefs_pending_idx` (0049) — дёшево даже при
    большой истории разборов. None — резолвить нечего (нет разборов или все уже resolution!='pending').
    """
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLS} from interview_debriefs "
        "where vacancy_id = $1 and resolution = 'pending' and account_id = $2 "
        "order by created_at desc, id desc limit 1",
        vacancy_id,
        account_id,
    )
    return DebriefRecord(**row_to_dict(row)) if row else None


async def mark_debrief_resolution(
    debrief_id: int,
    resolution: str,
    note: str = "",
    *,
    account_id: int,
    db: Executor | None = None,
) -> DebriefRecord | None:
    """Проставить исход разбора (advanced/rejected/pending) + заметку LLM-классификатора."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"update interview_debriefs set resolution = $2, resolved_at = now(), resolved_note = $3 "
        f"where id = $1 and account_id = $4 returning {_COLS}",
        debrief_id,
        resolution,
        note,
        account_id,
    )
    return DebriefRecord(**row_to_dict(row)) if row else None


async def update_transcript(
    debrief_id: int, transcript: str, *, account_id: int, db: Executor | None = None
) -> DebriefRecord | None:
    """UX5-5: точечная правка текста транскрипта (дровер-чат) без перезапуска LLM-анализа.

    Обнуляет `analysis.transcript_turns` — старая LLM-сегментация на реплики относится к старому
    тексту; фронт (`TranscriptChat`) откатывается на рендер целым абзацем, пока разбор не
    перезапустят вручную. По образцу `mark_debrief_resolution` — точечный UPDATE, без пересборки
    остальных полей analysis.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "update interview_debriefs set transcript = $2, "
        "analysis = jsonb_set(coalesce(analysis, '{}'::jsonb), '{transcript_turns}', '[]'::jsonb, true) "
        f"where id = $1 and account_id = $3 returning {_COLS}",
        debrief_id,
        transcript,
        account_id,
    )
    return DebriefRecord(**row_to_dict(row)) if row else None


async def load_debrief_stage_index(
    *, account_id: int, db: Executor | None = None
) -> list[tuple[str, str]]:
    """Пары (vacancy_id, stage) — где расшифровка уже вставлена и разобрана.

    Нужна рельсу Скринингов/Техничек: карточка вакансии показывает отметку «расшифровка есть»
    без похода за полной историей разборов на каждую карточку (это N запросов на список).
    Только ключи — ни транскрипта, ни разбора здесь не отдаём.
    """
    db = db or get_pool()
    rows = await db.fetch(
        "select distinct vacancy_id, stage from interview_debriefs where account_id = $1",
        account_id,
    )
    return [(str(r["vacancy_id"]), str(r["stage"])) for r in rows]


async def load_all_debriefs(
    limit: int = 300, *, account_id: int, db: Executor | None = None
) -> list[DebriefRecord]:
    """Все разборы по всем вакансиям аккаунта (свежие первыми) — RD-23: «Прогресс» смотрит на
    аккаунт целиком (график впечатления, готовность по форматам), не на одну вакансию."""
    db = db or get_pool()
    capped = min(max(limit, 1), 1000)
    rows = await db.fetch(
        f"select {_COLS} from interview_debriefs where account_id = $2 "
        "order by created_at desc, id desc limit $1",
        capped,
        account_id,
    )
    return [DebriefRecord(**row_to_dict(r)) for r in rows]


__all__ = [
    "DebriefRecord",
    "get_debrief",
    "save_debrief",
    "load_debrief_history",
    "load_debrief_stage_index",
    "load_latest_pending_debrief",
    "mark_debrief_resolution",
    "update_transcript",
    "load_all_debriefs",
]
