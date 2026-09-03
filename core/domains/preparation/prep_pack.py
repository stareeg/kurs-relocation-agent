"""Repository брифа подготовки под собес: один бриф на (vacancy_id, stage).

НЕ накопительная история (в отличие от `core.domains.preparation.debrief`): перегенерация затирает
предыдущий текст, персист вызывающий (роутер), чтобы фронт мог показать diff кандидата до
сохранения.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool, row_to_dict

logger = logging.getLogger(__name__)

_COLS = "vacancy_id, stage, content, updated_at, input_hash"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class PrepPackDocument(BaseModel):
    """Сохранённый бриф подготовки. `updated_at` — None, если ещё не собирали."""

    vacancy_id: str
    stage: str
    content: str = ""
    updated_at: datetime | None = None
    input_hash: str = ""


async def get_prep_pack(
    vacancy_id: str, stage: str, *, account_id: int, db: Executor | None = None
) -> PrepPackDocument:
    """Прочитать сохранённый бриф. Нет PG / нет строки → пустой бриф (вкладка грузится)."""
    db = db or get_pool()
    try:
        row = await db.fetchrow(
            f"select {_COLS} from prep_packs where vacancy_id = $1 and stage = $2 "
            "and account_id = $3",
            vacancy_id,
            stage,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой бриф
        logger.debug("prep_pack: чтение недоступно (нет PG?): %s", exc)
        return PrepPackDocument(vacancy_id=vacancy_id, stage=stage)
    if row is None:
        return PrepPackDocument(vacancy_id=vacancy_id, stage=stage)
    d = row_to_dict(row)
    return PrepPackDocument(
        vacancy_id=vacancy_id,
        stage=stage,
        content=d.get("content", "") or "",
        updated_at=_aware(d.get("updated_at")),
        input_hash=str(d.get("input_hash") or ""),
    )


async def save_prep_pack(
    vacancy_id: str,
    stage: str,
    content: str,
    *,
    input_hash: str = "",
    account_id: int,
    db: Executor | None = None,
) -> PrepPackDocument:
    """Перезаписать бриф (upsert по account_id+vacancy_id+stage). Возвращает свежий документ.

    `input_hash` — хэш входа, которым собран этот бриф; по нему `regenerate_prep_pack`
    решает, можно ли отдать сохранённое вместо повторного вызова LLM.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into prep_packs (account_id, vacancy_id, stage, content, updated_at, input_hash) "
        "values ($1, $2, $3, $4, now(), $5) "
        "on conflict (account_id, vacancy_id, stage) do update set "
        "content = excluded.content, updated_at = now(), input_hash = excluded.input_hash "
        f"returning {_COLS}",
        account_id,
        vacancy_id,
        stage,
        content,
        input_hash,
    )
    assert row is not None
    d = row_to_dict(row)
    return PrepPackDocument(
        vacancy_id=vacancy_id,
        stage=stage,
        content=d.get("content", "") or "",
        updated_at=_aware(d.get("updated_at")),
        input_hash=str(d.get("input_hash") or ""),
    )


__all__ = ["PrepPackDocument", "get_prep_pack", "save_prep_pack"]
