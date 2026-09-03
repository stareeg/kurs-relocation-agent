"""Персистентность пропущенных вакансий per vacancy_id (Postgres, `skipped_vacancies`).

"skip" — решение «не подавать», ОРТОГОНАЛЬНО статусу воронки (`jobs.status`): отдельная таблица,
БЕЗ FK на jobs (пропуск можно зафиксировать вручную для вакансии, которой нет в jobs).

`save_skipped` — upsert по vacancy_id: `created_at` иммутабелен, `scored_at` и метаданные
(url/title/company/score/recommendation/skip_reason) освежаются. Авто-запись после скоринга
(recommendation=skip) — в `core.domains.opportunities.persist`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from core.domains.opportunities.skip_reasons import canonical_skip_reason
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLUMNS = (
    "id, vacancy_id, url, title, company, overall_score, recommendation, "
    "skip_reason, canonical_reason, scored_at, created_at"
)
_REASON_MAX = 500  # причина усекается до 500 символов


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetime → UTC-aware (timestamptz).

    job.scored_at из PG уже aware, ручной — может naive.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class SkippedVacancy(BaseModel):
    """Пропущенная вакансия — решение «не подавать»."""

    id: int | None = None
    vacancy_id: str
    skip_reason: str
    canonical_reason: str | None = None
    url: str | None = None
    title: str | None = None
    company: str | None = None
    overall_score: int | None = None
    recommendation: str | None = None
    scored_at: datetime | None = None
    created_at: datetime | None = None


async def save_skipped(
    vacancy_id: str,
    skip_reason: str,
    *,
    url: str | None = None,
    title: str | None = None,
    company: str | None = None,
    overall_score: int | None = None,
    recommendation: str | None = None,
    scored_at: datetime | None = None,
    canonical_reason: str | None = None,
    account_id: int,
    db: Executor | None = None,
) -> SkippedVacancy:
    """Upsert по (account_id, vacancy_id) — HH id уникален только в рамках аккаунта (Этап 3).

    created_at иммутабелен, scored_at/метаданные освежаются. `canonical_reason` —
    нормализованная каноническая причина; явный аргумент используется как есть (каллер уже
    канонизировал сам, обычно чтобы синхронно решить что-то по канону — см. `POST /skip`),
    иначе выводится здесь же через `canonical_skip_reason` (Этап 7 §7.1) — колонка больше не
    остаётся `NULL` ни для одного вызывающего, включая `skip_job`/`_apply_archive_disposition`.
    """
    if not vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    reason = (skip_reason or "").strip()[:_REASON_MAX]
    canonical = ((canonical_reason or "").strip() or canonical_skip_reason(skip_reason))[
        :_REASON_MAX
    ]
    when = _aware(scored_at) or _now()
    row = await db.fetchrow(
        "insert into skipped_vacancies "
        "(vacancy_id, url, title, company, overall_score, recommendation, skip_reason, "
        "canonical_reason, scored_at, account_id) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) "
        "on conflict (account_id, vacancy_id) do update set "
        "url = excluded.url, title = excluded.title, company = excluded.company, "
        "overall_score = excluded.overall_score, recommendation = excluded.recommendation, "
        "skip_reason = excluded.skip_reason, canonical_reason = excluded.canonical_reason, "
        "scored_at = excluded.scored_at "
        f"returning {_COLUMNS}",
        vacancy_id,
        url,
        title,
        company,
        overall_score,
        recommendation,
        reason,
        canonical,
        when,
        account_id,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return SkippedVacancy(**row_to_dict(row))


async def load_skipped_list(
    limit: int = 50, *, account_id: int, db: Executor | None = None
) -> list[SkippedVacancy]:
    """Последние пропущенные (порядок scored_at desc). limit сверху ограничен 200."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    rows = await db.fetch(
        f"select {_COLUMNS} from skipped_vacancies where account_id = $2 "
        "order by scored_at desc limit $1",
        capped,
        account_id,
    )
    return [SkippedVacancy(**row_to_dict(r)) for r in rows]


async def is_skipped(vacancy_id: str, *, account_id: int, db: Executor | None = None) -> bool:
    """Быстрая проверка «вакансия пропущена» (фильтр discovery, чтобы не пере-скорить)."""
    if not vacancy_id:
        return False
    db = db or get_pool()
    row = await db.fetchrow(
        "select 1 from skipped_vacancies where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    return row is not None


async def get_skipped_ids(
    vacancy_ids: list[str], *, account_id: int, db: Executor | None = None
) -> set[str]:
    """Карта-множество пропущенных vacancy_id из пачки — один запрос вместо `is_skipped` в цикле
    (лог «Просмотра»: живой статус пропуска на строку, см. discovery_session._attach_live_job_state)."""
    ids = [v for v in vacancy_ids if v]
    if not ids:
        return set()
    db = db or get_pool()
    rows = await db.fetch(
        "select vacancy_id from skipped_vacancies where vacancy_id = any($1) and account_id = $2",
        ids,
        account_id,
    )
    return {r["vacancy_id"] for r in rows}


async def get_skipped(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> SkippedVacancy | None:
    """Запись пропуска с причиной (в отличие от `is_skipped` — не только факт).

    Нужна `/funnel/{id}`: расширение теряет `skip_reason` на новой вкладке/после очистки
    storage (сам факт пропуска у него переживает перезагрузку через `skipped: bool`, причина —
    нет), из-за чего done-state «Пропущено» показывался без причины.
    """
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLUMNS} from skipped_vacancies where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    return SkippedVacancy(**row_to_dict(row)) if row is not None else None


async def delete_skipped(vacancy_id: str, *, account_id: int, db: Executor | None = None) -> bool:
    """Снять пропуск (вернуть вакансию в воронку). True, если запись была и удалена.

    Решение «не подавать» отменяемо: пользователь возвращает вакансию из «Пропущено» в
    активный путь. Ортогонально статусу воронки (`jobs.status`) — его не трогаем.
    """
    if not vacancy_id:
        return False
    db = db or get_pool()
    result = await db.execute(
        "delete from skipped_vacancies where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    # asyncpg возвращает командный тег вида "DELETE <n>"; n>0 => запись была.
    return str(result).rsplit(" ", 1)[-1] not in ("", "0")


async def count_skipped(*, account_id: int, db: Executor | None = None) -> int:
    db = db or get_pool()
    return int(
        await db.fetchval(
            "select count(*) from skipped_vacancies where account_id = $1", account_id
        )
        or 0
    )
