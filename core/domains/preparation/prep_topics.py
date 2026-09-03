"""Repository тем подготовки: готовность weak/medium/confident по вакансии+этапу."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from core.domains.preparation.models import MockMastery
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = "id, vacancy_id, stage, topic, level, packs_reviewed, created_at, updated_at"
_LEVEL_ORDER = ("weak", "medium", "confident")
# Сколько раскрытий вопроса нужно на текущем уровне, чтобы подняться на ступень.
# weak→medium: 1; medium→confident: 2. Счётчик packs_reviewed сбрасывается после бампа.
_REVIEWS_TO_BUMP: dict[str, int] = {"weak": 1, "medium": 2}


class PrepTopicRow(BaseModel):
    id: int | None = None
    vacancy_id: str
    stage: str
    topic: str = Field(min_length=1, max_length=200)
    level: MockMastery = "weak"
    packs_reviewed: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _next_level(level: str) -> MockMastery:
    try:
        idx = _LEVEL_ORDER.index(level)
    except ValueError:
        return "medium"
    if idx >= len(_LEVEL_ORDER) - 1:
        return "confident"
    return _LEVEL_ORDER[idx + 1]  # type: ignore[return-value]


def apply_review_bump(level: str, packs_reviewed: int) -> tuple[MockMastery, int]:
    """После одного раскрытия: новый (level, packs_reviewed).

    weak→medium за 1 клик; medium→confident за 2 клика на medium. После бампа счётчик = 0.
    """
    packs = packs_reviewed + 1
    needed = _REVIEWS_TO_BUMP.get(level)
    if needed is not None and packs >= needed and level != "confident":
        return _next_level(level), 0
    resolved: MockMastery = level if level in _LEVEL_ORDER else "medium"  # type: ignore[assignment]
    return resolved, packs


async def load_prep_topics(
    vacancy_id: str, stage: str, *, account_id: int, db: Executor | None = None
) -> list[PrepTopicRow]:
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_COLS} from prep_topics "
        "where vacancy_id = $1 and stage = $2 and account_id = $3 order by topic",
        vacancy_id,
        stage,
        account_id,
    )
    return [PrepTopicRow(**row_to_dict(r)) for r in rows]


async def replace_prep_topics(
    vacancy_id: str,
    stage: str,
    topics: list[str],
    *,
    account_id: int,
    db: Executor | None = None,
) -> list[PrepTopicRow]:
    """Заменить набор тем (после LLM-генерации). Уровни существующих тем сохраняем."""
    db = db or get_pool()
    existing = {
        t.topic: t for t in await load_prep_topics(vacancy_id, stage, account_id=account_id, db=db)
    }
    await db.execute(
        "delete from prep_topics where vacancy_id = $1 and stage = $2 and account_id = $3",
        vacancy_id,
        stage,
        account_id,
    )
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in topics:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        cleaned.append(name[:200])
    if not cleaned:
        return []
    await db.executemany(
        "insert into prep_topics (account_id, vacancy_id, stage, topic, level, packs_reviewed) "
        "values ($1, $2, $3, $4, $5, $6)",
        [
            (
                account_id,
                vacancy_id,
                stage,
                name,
                existing[name].level if name in existing else "weak",
                existing[name].packs_reviewed if name in existing else 0,
            )
            for name in cleaned
        ],
    )
    return await load_prep_topics(vacancy_id, stage, account_id=account_id, db=db)


async def review_prep_topics(
    vacancy_id: str,
    stage: str,
    topics: list[str],
    *,
    account_id: int,
    db: Executor | None = None,
) -> list[PrepTopicRow]:
    """Засчитать раскрытие ответа по темам: +1 packs_reviewed; бамп уровня по порогу.

    weak→medium после 1 раскрытия; medium→confident после 2 на уровне medium.
    После бампа счётчик обнуляется (следующая ступень считается заново).
    """
    db = db or get_pool()
    names = []
    seen: set[str] = set()
    for raw in topics:
        name = (raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name[:200])
    if not names:
        return await load_prep_topics(vacancy_id, stage, account_id=account_id, db=db)

    for name in names:
        row = await db.fetchrow(
            f"select {_COLS} from prep_topics "
            "where vacancy_id = $1 and stage = $2 and topic = $3 and account_id = $4",
            vacancy_id,
            stage,
            name,
            account_id,
        )
        if row is None:
            # Новая тема с первого раскрытия: сразу medium (порог weak = 1).
            await db.execute(
                "insert into prep_topics (account_id, vacancy_id, stage, topic, level, "
                "packs_reviewed) values ($1, $2, $3, $4, 'medium', 0)",
                account_id,
                vacancy_id,
                stage,
                name,
            )
            continue
        level, packs = apply_review_bump(str(row["level"]), int(row["packs_reviewed"]))
        await db.execute(
            "update prep_topics set packs_reviewed = $1, level = $2, updated_at = now() "
            "where vacancy_id = $3 and stage = $4 and topic = $5 and account_id = $6",
            packs,
            level,
            vacancy_id,
            stage,
            name,
            account_id,
        )
    return await load_prep_topics(vacancy_id, stage, account_id=account_id, db=db)


__all__ = [
    "PrepTopicRow",
    "apply_review_bump",
    "load_prep_topics",
    "replace_prep_topics",
    "review_prep_topics",
]
