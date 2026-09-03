"""Персистентность подготовки к собеседованию и prep-напоминаний (Postgres).

questions/responses хранятся как jsonb — модуль работает со списками dict, типизацию вопроса
в `PrepQuestion` делают потребители (`core.domains.preparation.interview.prep`, роутеры).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.domains.preparation.models import PrepQuestion
from core.platform.db.pool import Executor, get_pool, row_to_dict

_SESSION_COLS = (
    "id, interview_id, vacancy_id, stage, generated_at, questions, responses, status, finished_at"
)
_REMINDER_COLS = (
    "id, interview_id, vacancy_id, company, position, stage, interview_dt, fire_at, "
    "chat_id, fired, created_at"
)
# Статусы, при которых подготовка считается завершённой (проставляем finished_at).
_FINISHED_STATUSES = ("finished", "skipped")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetime → UTC-aware (timestamptz). PG-времена уже aware, ручные — могут быть naive."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class PrepSession(BaseModel):
    """Сессия подготовки: вопросы по этапу + ответы кандидата с фидбеком."""

    id: int | None = None
    interview_id: int | None = None
    vacancy_id: str
    stage: str = "screening"
    generated_at: datetime | None = None
    questions: list[dict[str, Any]] = Field(default_factory=list)
    responses: list[dict[str, Any]] = Field(default_factory=list)
    status: str = "generated"
    finished_at: datetime | None = None


class PrepReminder(BaseModel):
    """Напоминание подготовки до собеседования (fire_at — когда послать prep-пинг)."""

    id: int | None = None
    interview_id: int | None = None
    vacancy_id: str
    company: str = ""
    position: str = ""
    stage: str = "screening"
    interview_dt: datetime
    fire_at: datetime
    chat_id: int
    fired: bool = False
    created_at: datetime | None = None


# ---- prep sessions ----


async def save_prep_session(
    session: PrepSession, *, account_id: int, db: Executor | None = None
) -> PrepSession:
    """Вставить новую сессию подготовки; вернуть её с проставленным id."""
    if not session.vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into prep_sessions "
        "(account_id, interview_id, vacancy_id, stage, generated_at, questions, responses, "
        "status, finished_at) "
        "values ($1, $2, $3, $4, coalesce($5, now()), $6, $7, $8, $9) "
        f"returning {_SESSION_COLS}",
        account_id,
        session.interview_id,
        session.vacancy_id,
        session.stage,
        _aware(session.generated_at),
        session.questions,
        session.responses,
        session.status,
        _aware(session.finished_at),
    )
    assert row is not None
    return PrepSession(**row_to_dict(row))


async def update_prep_responses(
    prep_id: int,
    responses: list[dict[str, Any]],
    status: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Обновить ответы и статус; finished_at проставляется на терминальном статусе."""
    db = db or get_pool()
    finished = _now() if status in _FINISHED_STATUSES else None
    await db.execute(
        "update prep_sessions set responses = $1, status = $2, "
        "finished_at = coalesce($3, finished_at) where id = $4 and account_id = $5",
        responses,
        status,
        finished,
        prep_id,
        account_id,
    )


async def update_prep_session_questions(
    prep_id: int, questions: list[dict[str, Any]], *, account_id: int, db: Executor | None = None
) -> None:
    """Переписать `questions` сессии — RD-22, матчер проставляет `outcome` на элементах после
    разбора собеса. Ответы/статус не трогает (отдельный `update_prep_responses`)."""
    db = db or get_pool()
    await db.execute(
        "update prep_sessions set questions = $1 where id = $2 and account_id = $3",
        questions,
        prep_id,
        account_id,
    )


async def append_prep_questions(
    vacancy_id: str,
    stage: str,
    new_questions: list[PrepQuestion],
    *,
    account_id: int,
    db: Executor | None = None,
) -> PrepSession:
    """Дописать пачку вопросов из чата подготовки в последнюю сессию (vacancy_id, stage), PREP-3.

    Дедуп по точному совпадению текста вопроса — «ещё пачку по X» два раза подряд не плодит
    дубли. Сессии под этот этап ещё нет — заводит новую, как первую генерацию.
    """
    db = db or get_pool()
    items = [q.model_dump() for q in new_questions]

    sessions = await load_prep_history(vacancy_id, limit=50, account_id=account_id, db=db)
    match = next((s for s in sessions if s.stage == stage), None)

    if match is None:
        return await save_prep_session(
            PrepSession(vacancy_id=vacancy_id, stage=stage, questions=items, status="generated"),
            account_id=account_id,
            db=db,
        )

    existing_texts = {q.get("text") for q in match.questions if isinstance(q, dict)}
    fresh = [q for q in items if q.get("text") not in existing_texts]
    if fresh:
        merged = [*match.questions, *fresh]
        assert match.id is not None  # всегда есть id — сессия только что прочитана из PG
        await update_prep_session_questions(match.id, merged, account_id=account_id, db=db)
        match.questions = merged
    return match


async def load_prep_session(
    prep_id: int, *, account_id: int, db: Executor | None = None
) -> PrepSession | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_SESSION_COLS} from prep_sessions where id = $1 and account_id = $2",
        prep_id,
        account_id,
    )
    return PrepSession(**row_to_dict(row)) if row else None


async def load_prep_history(
    vacancy_id: str, limit: int = 10, *, account_id: int, db: Executor | None = None
) -> list[PrepSession]:
    """История подготовок по вакансии (свежие первыми)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_SESSION_COLS} from prep_sessions where vacancy_id = $1 and account_id = $2 "
        "order by generated_at desc, id desc limit $3",
        vacancy_id,
        account_id,
        capped,
    )
    return [PrepSession(**row_to_dict(r)) for r in rows]


async def load_active_prep_sessions(
    limit: int = 10, *, db: Executor | None = None
) -> list[PrepSession]:
    """Незавершённые подготовки (generated/in_progress) для снапшота состояния (state-export).

    Кросс-аккаунтный системный снимок (как GC вложений/маркет-агрегация, план §1) — без
    `account_id`: снапшот состояния процесса, не ответ на конкретный запрос аккаунта.
    """
    db = db or get_pool()
    capped = min(max(limit, 1), 100)
    rows = await db.fetch(
        f"select {_SESSION_COLS} from prep_sessions "
        "where status in ('generated', 'in_progress') "
        "order by generated_at desc, id desc limit $1",
        capped,
    )
    return [PrepSession(**row_to_dict(r)) for r in rows]


# ---- reminders ----


async def schedule_reminder(
    *,
    interview_id: int | None,
    vacancy_id: str,
    company: str = "",
    position: str = "",
    stage: str = "screening",
    interview_dt: datetime,
    fire_at: datetime,
    chat_id: int,
    account_id: int,
    db: Executor | None = None,
) -> PrepReminder:
    """Запланировать prep-напоминание. Идемпотентно: дубль (interview_id, fire_at) среди не-fired
    не плодим."""
    db = db or get_pool()
    fire = _aware(fire_at)
    if interview_id is not None:
        existing = await db.fetchrow(
            f"select {_REMINDER_COLS} from prep_reminders "
            "where interview_id = $1 and fire_at = $2 and fired = false and account_id = $3",
            interview_id,
            fire,
            account_id,
        )
        if existing:
            return PrepReminder(**row_to_dict(existing))
    row = await db.fetchrow(
        "insert into prep_reminders "
        "(account_id, interview_id, vacancy_id, company, position, stage, interview_dt, "
        "fire_at, chat_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9) "
        f"returning {_REMINDER_COLS}",
        account_id,
        interview_id,
        vacancy_id,
        company,
        position,
        stage,
        _aware(interview_dt),
        fire,
        chat_id,
    )
    assert row is not None
    return PrepReminder(**row_to_dict(row))


async def load_due_reminders(
    now: datetime | None = None, *, db: Executor | None = None
) -> list[PrepReminder]:
    """Созревшие и ещё не отправленные напоминания (fire_at <= now).

    Кросс-аккаунтная фоновая петля (bot_app.services.prep_scheduler) — как GC вложений/маркет-
    агрегация (план §1), без `account_id`: доставка идёт по денормализованному `chat_id` строки,
    не по личности запроса.
    """
    db = db or get_pool()
    when = _aware(now) or _now()
    rows = await db.fetch(
        f"select {_REMINDER_COLS} from prep_reminders "
        "where fired = false and fire_at <= $1 order by fire_at asc",
        when,
    )
    return [PrepReminder(**row_to_dict(r)) for r in rows]


async def mark_reminder_fired(reminder_id: int, *, db: Executor | None = None) -> None:
    """Системная петля уже прочитала строку через `load_due_reminders` без фильтра — тот же
    системный путь, `account_id` здесь не нужен (план §1)."""
    db = db or get_pool()
    await db.execute("update prep_reminders set fired = true where id = $1", reminder_id)


async def clear_prep_questions(
    vacancy_id: str, stage: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Обнулить вопросы последней prep-сессии под (vacancy, stage). True если сессия была."""
    db = db or get_pool()
    sessions = await load_prep_history(vacancy_id, limit=50, account_id=account_id, db=db)
    match = next((s for s in sessions if s.stage == stage), None)
    if match is None or match.id is None:
        return False
    await update_prep_session_questions(match.id, [], account_id=account_id, db=db)
    return True
