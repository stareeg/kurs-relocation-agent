"""Персистентность enrichment от HR per vacancy_id (Postgres, `vacancy_enrichment`).

`merge_enrichment` мержит непустые HR-поля поверх существующих, всегда освежает
`last_hr_contact_at`, дебриф дописывает без дублирования. Этапы собеседований —
отдельная таблица (`core.domains.preparation.interview_stages`).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLUMNS = (
    "vacancy_id, salary_hr_range, salary_match, format_clarified, team_size, "
    "last_hr_contact_at, hr_contact_summary, interview_debrief, hr_link, updated_at"
)


class VacancyEnrichment(BaseModel):
    vacancy_id: str
    salary_hr_range: str = ""
    salary_match: str | None = None  # 'yes' | 'no' | 'unclear' (валидируется CHECK в БД)
    format_clarified: str = ""
    team_size: str = ""
    last_hr_contact_at: datetime | None = None
    hr_contact_summary: str = ""
    interview_debrief: str = ""
    hr_link: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _merge_debrief_text(existing: str, new: str, *, max_len: int = 12000) -> str:
    """Дописать дебриф без дублирования блоков."""
    old = (existing or "").strip()
    add = (new or "").strip()
    if not add:
        return old[:max_len]
    if not old:
        return add[:max_len]
    if add in old:
        return old[:max_len]
    return f"{old}\n\n---\n{add}"[:max_len]


async def load_enrichment(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> VacancyEnrichment | None:
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLUMNS} from vacancy_enrichment where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    return VacancyEnrichment(**row_to_dict(row)) if row else None


async def merge_enrichment(
    vacancy_id: str,
    *,
    salary_hr_range: str = "",
    salary_match: str | None = None,
    format_clarified: str = "",
    team_size: str = "",
    hr_contact_summary: str = "",
    interview_debrief: str = "",
    hr_link: str = "",
    contact_at: datetime | None = None,
    account_id: int,
    db: Executor | None = None,
) -> VacancyEnrichment:
    """Upsert: непустые поля поверх существующих, last_hr_contact_at всегда освежается."""
    if not vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    now = contact_at or datetime.now(UTC)
    existing = await load_enrichment(vacancy_id, account_id=account_id, db=db)

    merged = VacancyEnrichment(
        vacancy_id=vacancy_id,
        salary_hr_range=salary_hr_range or (existing.salary_hr_range if existing else ""),
        salary_match=salary_match or (existing.salary_match if existing else None),
        format_clarified=format_clarified or (existing.format_clarified if existing else ""),
        team_size=team_size or (existing.team_size if existing else ""),
        last_hr_contact_at=now,
        hr_contact_summary=hr_contact_summary or (existing.hr_contact_summary if existing else ""),
        interview_debrief=_merge_debrief_text(
            existing.interview_debrief if existing else "", interview_debrief
        ),
        hr_link=hr_link or (existing.hr_link if existing else ""),
        updated_at=now,
    )

    row = await db.fetchrow(
        f"""
        insert into vacancy_enrichment ({_COLUMNS}, account_id)
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        on conflict (account_id, vacancy_id) do update set
            salary_hr_range = excluded.salary_hr_range,
            salary_match = excluded.salary_match,
            format_clarified = excluded.format_clarified,
            team_size = excluded.team_size,
            last_hr_contact_at = excluded.last_hr_contact_at,
            hr_contact_summary = excluded.hr_contact_summary,
            interview_debrief = excluded.interview_debrief,
            hr_link = excluded.hr_link,
            updated_at = excluded.updated_at
        returning {_COLUMNS}
        """,
        merged.vacancy_id,
        merged.salary_hr_range,
        merged.salary_match,
        merged.format_clarified,
        merged.team_size,
        merged.last_hr_contact_at,
        merged.hr_contact_summary,
        merged.interview_debrief,
        merged.hr_link,
        merged.updated_at,
        account_id,
    )
    assert row is not None
    return VacancyEnrichment(**row_to_dict(row))


# Терминальные статусы воронки — по ним HR молчит
# не зря, в digest не зовём. Архив добавлен к терминальным (Отказ/Оффер): нагонять по
# вручную заархивированной вакансии — баг.
_DEAD_FUNNEL_STATUSES = ("Отказ", "Оффер", "Архив")


async def load_stale_hr_contacts(
    days: int = 5, *, limit: int = 20, account_id: int, db: Executor | None = None
) -> list[VacancyEnrichment]:
    """Активные вакансии, где HR молчит больше N дней (digest «давно нет ответа HR»).

    Джойн на `jobs`:
    исключаем терминальные статусы, сортируем по давности последнего контакта.
    """
    db = db or get_pool()
    e_cols = ", ".join(f"e.{c}" for c in _COLUMNS.split(", "))
    rows = await db.fetch(
        f"""
        select {e_cols} from vacancy_enrichment e
        join jobs j on j.account_id = e.account_id and j.vacancy_id = e.vacancy_id
        where e.last_hr_contact_at is not null
          and e.last_hr_contact_at <= now() - make_interval(days => $1)
          and (j.status is null or j.status <> all($3::text[]))
          and e.account_id = $4
        order by e.last_hr_contact_at asc
        limit $2
        """,
        days,
        limit,
        list(_DEAD_FUNNEL_STATUSES),
        account_id,
    )
    return [VacancyEnrichment(**row_to_dict(r)) for r in rows]
