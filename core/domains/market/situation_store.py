"""Repository кэша LLM-сводки ситуации: персист последней сводки + чтение latest.

По образцу `core.domains.preparation.debrief` / `core.domains.profile.resume_stats`:
свои Pydantic-модели,
без зависимости от api/bot. `narrative` хранится как jsonb (структурный вывод
`SituationNarrative`, schema_version=7 после D-08 — 2 поля: вывод + шаги с адресатом).
Каждая генерация пишет новую строку,
latest = текущий кэш. «Рынок» читает latest без LLM-вызова, кнопка «Разобрать ситуацию»
пишет новую (LLM = деньги, не на каждый заход).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLS = "id, created_at, summary, narrative, schema_version"


class SituationRecord(BaseModel):
    """Сохранённая сводка ситуации: краткое резюме (денорм) + полный структурный вывод в jsonb."""

    id: int | None = None
    created_at: datetime | None = None
    summary: str = ""
    narrative: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = 1


async def save_situation(
    summary: str,
    narrative: dict[str, Any],
    *,
    account_id: int,
    schema_version: int = 1,
    db: Executor | None = None,
) -> SituationRecord:
    """Записать новую сводку аккаунта (append-only). Возвращает сохранённую строку с id/created_at."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into situation_narratives (account_id, summary, narrative, schema_version) "
        f"values ($1, $2, $3, $4) returning {_COLS}",
        account_id,
        summary,
        narrative,
        schema_version,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return SituationRecord(**row_to_dict(row))


async def load_latest_situation(
    *, account_id: int, db: Executor | None = None
) -> SituationRecord | None:
    """Последняя сохранённая сводка аккаунта (кэш для GET). Нет строк → None."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLS} from situation_narratives where account_id = $1 "
        "order by created_at desc, id desc limit 1",
        account_id,
    )
    return SituationRecord(**row_to_dict(row)) if row is not None else None


async def clear_situation(*, account_id: int, db: Executor | None = None) -> None:
    """Сбросить кэш сводки аккаунта. Следующий GET вернёт None — нужна новая генерация."""
    if not account_id:
        return
    db = db or get_pool()
    await db.execute("delete from situation_narratives where account_id = $1", account_id)


__all__ = ["SituationRecord", "save_situation", "load_latest_situation", "clear_situation"]
