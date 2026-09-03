"""Персистентность привязок HR ↔ vacancy_id (Postgres, `hr_vacancy_links`).

Один HR (`hr_key`) — несколько вакансий; разрешение vacancy_id для входящего HR-сообщения:
явный id > совпадение компании > единственная привязка.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLUMNS = "hr_key, vacancy_id, company, position, hr_link, updated_at"


class HrVacancyLink(BaseModel):
    hr_key: str
    vacancy_id: str
    company: str = ""
    position: str = ""
    hr_link: str = ""
    updated_at: datetime | None = None


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


async def register_hr_vacancy_link(
    *,
    hr_key: str,
    vacancy_id: str,
    company: str = "",
    position: str = "",
    hr_link: str = "",
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Upsert привязки HR↔вакансия. Пустой hr_link → сам hr_key."""
    if not hr_key or not vacancy_id:
        return
    db = db or get_pool()
    link = hr_link or hr_key
    await db.execute(
        "insert into hr_vacancy_links "
        "(hr_key, vacancy_id, company, position, hr_link, updated_at, account_id) "
        "values ($1, $2, $3, $4, $5, now(), $6) "
        "on conflict (account_id, hr_key, vacancy_id) do update set "
        "company = excluded.company, position = excluded.position, "
        "hr_link = excluded.hr_link, updated_at = excluded.updated_at",
        hr_key,
        vacancy_id,
        company,
        position,
        link,
        account_id,
    )


async def list_vacancy_ids_for_hr(
    hr_key: str, *, account_id: int, db: Executor | None = None
) -> list[str]:
    """Все vacancy_id этого HR, свежие первыми."""
    if not hr_key:
        return []
    db = db or get_pool()
    rows = await db.fetch(
        "select vacancy_id from hr_vacancy_links "
        "where hr_key = $1 and account_id = $2 order by updated_at desc",
        hr_key,
        account_id,
    )
    return [str(r["vacancy_id"]) for r in rows if r["vacancy_id"]]


async def link_row(
    hr_key: str, vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> HrVacancyLink | None:
    """Одна привязка по hr_key + vacancy_id."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLUMNS} from hr_vacancy_links "
        "where hr_key = $1 and vacancy_id = $2 and account_id = $3",
        hr_key,
        vacancy_id,
        account_id,
    )
    return HrVacancyLink(**row_to_dict(row)) if row else None


async def resolve_vacancy_id_for_hr(
    *,
    hr_key: str,
    company: str = "",
    position: str = "",  # noqa: ARG001 — совместимость сигнатуры; решает id/компания
    preferred_vacancy_id: str = "",
    account_id: int,
    db: Executor | None = None,
) -> str | None:
    """Выбрать vacancy_id для HR: явный id > совпадение компании > единственная привязка."""
    if preferred_vacancy_id:
        return preferred_vacancy_id

    db = db or get_pool()
    ids = await list_vacancy_ids_for_hr(hr_key, account_id=account_id, db=db)
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]

    cn = _norm(company)
    if cn and cn != _norm("неизвестнаякомпания"):
        for vid in ids:
            row = await link_row(hr_key, vid, account_id=account_id, db=db)
            if not row:
                continue
            rc = _norm(row.company)
            if rc and (cn in rc or rc in cn):
                return vid

    return None
