"""Repository карты компетенций: леджер уровня владения темой от собеса к собесу.

По образцу `core.domains.preparation.debrief`/`core.domains.pipeline.stage_outcome`: своя Pydantic-модель, без зависимости
от api/bot, append-only (каждый дебриф добавляет строки, не перезаписывает прошлые - иначе не
построить траекторию weak -> confident). Канонизация тем (синонимы -> одна строка) - LLM-матчер
в `core.domains.preparation.interview.question_match`, здесь только персист уже канонизированных записей.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from core.domains.preparation.models import MockMastery
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = "id, topic_canon, level, evidence, vacancy_id, stage, debrief_id, created_at"


class CompetencyEntry(BaseModel):
    """Одна строка леджера: тема-канон + уровень на момент конкретного дебрифа."""

    id: int | None = None
    topic_canon: str = Field(min_length=1, max_length=200)
    level: MockMastery = "medium"
    evidence: str = ""
    vacancy_id: str
    stage: str
    debrief_id: int | None = None
    created_at: datetime | None = None


class TopicLatest(BaseModel):
    """Свежий уровень темы-канона - что видит прогресс-панель и prep_context (блок 3)."""

    topic_canon: str
    level: MockMastery
    evidence: str
    created_at: datetime


async def save_competency_entries(
    entries: list[CompetencyEntry], *, account_id: int, db: Executor | None = None
) -> None:
    """Дописать пачку строк леджера (одна пачка = один дебриф). Пустой список - no-op."""
    if not entries:
        return
    db = db or get_pool()
    await db.executemany(
        "insert into competency_ledger "
        "(account_id, topic_canon, level, evidence, vacancy_id, stage, debrief_id) "
        "values ($1, $2, $3, $4, $5, $6, $7)",
        [
            (account_id, e.topic_canon, e.level, e.evidence, e.vacancy_id, e.stage, e.debrief_id)
            for e in entries
        ],
    )


async def load_distinct_canon_topics(
    limit: int = 300, *, account_id: int, db: Executor | None = None
) -> list[str]:
    """Уже принятые названия тем (для канонизации новых записей одним LLM-вызовом)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 1000)
    rows = await db.fetch(
        "select topic_canon, max(created_at) as last_seen from competency_ledger "
        "where account_id = $2 group by topic_canon order by last_seen desc limit $1",
        capped,
        account_id,
    )
    return [r["topic_canon"] for r in rows]


async def load_latest_topic_levels(
    *, account_id: int, db: Executor | None = None
) -> list[TopicLatest]:
    """Свежий уровень КАЖДОЙ темы-канона (одна строка на тему - последняя по времени).

    Источник блока 3 prep_context: тема, ставшая confident, уходит из фокуса САМА -
    здесь просто самый свежий уровень, без истории.
    """
    db = db or get_pool()
    rows = await db.fetch(
        "select distinct on (topic_canon) topic_canon, level, evidence, created_at "
        "from competency_ledger where account_id = $1 order by topic_canon, created_at desc",
        account_id,
    )
    return [TopicLatest(**row_to_dict(r)) for r in rows]


async def load_all_entries(
    limit: int = 3000, *, account_id: int, db: Executor | None = None
) -> list[CompetencyEntry]:
    """Весь леджер аккаунта (свежие первыми, капнуто) - сырьё для агрегации трендов на «Прогрессе»."""
    db = db or get_pool()
    capped = min(max(limit, 1), 10000)
    rows = await db.fetch(
        f"select {_COLS} from competency_ledger where account_id = $2 "
        "order by created_at desc limit $1",
        capped,
        account_id,
    )
    return [CompetencyEntry(**row_to_dict(r)) for r in rows]


__all__ = [
    "CompetencyEntry",
    "TopicLatest",
    "save_competency_entries",
    "load_distinct_canon_topics",
    "load_latest_topic_levels",
    "load_all_entries",
]
