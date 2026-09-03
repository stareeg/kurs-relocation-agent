"""Repository статистики резюме: персист снимков агрегата + строк истории просмотров.

По образцу `core.domains.preparation.debrief`/`core.domains.opportunities.skipped`: свои Pydantic-модели, без зависимости от
api/bot. `raw` хранится как jsonb (исходный распарсенный блок страницы hh — на случай, если
понадобятся поля сверх денормализованных). Два сигнала с hh:

- `resume_stats` — снимок счётчиков (показы/просмотры/приглашения + недельные дельты). Накопление
  во времени даёт динамику отклика рынка. Дневная идемпотентность: за один день снимок с теми же
  счётчиками не дублируем (расширение шлёт на каждом заходе) — иначе серия зашумлена.
- `resume_views` — строка истории просмотра. Дедуп по натуральному ключу (employer, vacancy_url,
  viewed_at) через `on conflict do nothing`: повторный заход не плодит дубли.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict

# Снимки профиля getmatch — отдельный resume_id, не смешиваем с hh.
GETMATCH_PROFILE_RESUME_ID = "getmatch:profile"

_STAT_COLS = (
    "id, captured_at, resume_id, period, impressions, views, invitations, recommended_vacancies, "
    "views_delta, invitations_delta, raw, created_at"
)
_VIEW_COLS = "id, viewed_at, employer, vacancy_title, vacancy_url, resume_id, raw, created_at"
# account_id — фильтр WHERE, не проецируется в _STAT_COLS/_VIEW_COLS (ResumeStatSnapshot/
# ResumeView его не несут — это внутренняя изоляция, не поле ответа).


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetime → UTC-aware (timestamptz). PG-времена уже aware, ручные — могут быть naive."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class ResumeStatSnapshot(BaseModel):
    """Снимок агрегатных счётчиков резюме на момент времени."""

    id: int | None = None
    captured_at: datetime | None = None
    resume_id: str = ""
    period: str = "week"
    impressions: int = 0
    views: int = 0
    invitations: int = 0
    recommended_vacancies: int = 0
    views_delta: int = 0
    invitations_delta: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ResumeView(BaseModel):
    """Строка истории просмотра резюме (работодатель / вакансия / время)."""

    id: int | None = None
    viewed_at: datetime | None = None
    employer: str = ""
    vacancy_title: str = ""
    vacancy_url: str = ""
    resume_id: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


async def save_resume_stat(
    snapshot: ResumeStatSnapshot, *, account_id: int, db: Executor | None = None
) -> tuple[ResumeStatSnapshot, bool]:
    """Сохранить снимок аккаунта запроса с дневной идемпотентностью.

    Если за тот же день уже есть снимок этого резюме (в пределах аккаунта) с теми же
    счётчиками (показы/просмотры/приглашения) — возвращаем его, ничего не вставляя
    (`inserted=False`). Иначе пишем новый (`inserted=True`). Так серия не зашумляется
    повторными заходами на страницу с теми же числами.
    """
    db = db or get_pool()
    captured = _aware(snapshot.captured_at) or _now()
    existing = await db.fetchrow(
        f"select {_STAT_COLS} from resume_stats "
        "where account_id = $1 and resume_id = $2 and captured_at::date = $3::date "
        "and impressions = $4 and views = $5 and invitations = $6 and recommended_vacancies = $7 "
        "order by captured_at desc limit 1",
        account_id,
        snapshot.resume_id,
        captured,
        snapshot.impressions,
        snapshot.views,
        snapshot.invitations,
        snapshot.recommended_vacancies,
    )
    if existing is not None:
        return ResumeStatSnapshot(**row_to_dict(existing)), False

    row = await db.fetchrow(
        "insert into resume_stats "
        "(account_id, captured_at, resume_id, period, impressions, views, invitations, "
        " recommended_vacancies, views_delta, invitations_delta, raw) "
        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) "
        f"returning {_STAT_COLS}",
        account_id,
        captured,
        snapshot.resume_id,
        snapshot.period,
        snapshot.impressions,
        snapshot.views,
        snapshot.invitations,
        snapshot.recommended_vacancies,
        snapshot.views_delta,
        snapshot.invitations_delta,
        snapshot.raw,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    return ResumeStatSnapshot(**row_to_dict(row)), True


async def save_resume_views(
    rows: list[ResumeView], *, account_id: int, db: Executor | None = None
) -> int:
    """Сохранить строки истории аккаунта запроса с дедупом по натуральному ключу. Возвращает
    число новых строк."""
    if not rows:
        return 0
    db = db or get_pool()
    inserted = 0
    for view in rows:
        viewed = _aware(view.viewed_at) or _now()
        result = await db.execute(
            "insert into resume_views "
            "(account_id, viewed_at, employer, vacancy_title, vacancy_url, resume_id, raw) "
            "values ($1, $2, $3, $4, $5, $6, $7) "
            "on conflict (account_id, employer, vacancy_url, viewed_at) do nothing",
            account_id,
            viewed,
            view.employer,
            view.vacancy_title,
            view.vacancy_url,
            view.resume_id,
            view.raw,
        )
        # asyncpg отдаёт командный тег "INSERT 0 <n>"; n>0 => строка реально вставлена (не конфликт).
        if str(result).rsplit(" ", 1)[-1] not in ("", "0"):
            inserted += 1
    return inserted


async def list_resume_stats(
    since: datetime | None = None,
    limit: int = 365,
    *,
    account_id: int,
    until: datetime | None = None,
    db: Executor | None = None,
) -> list[ResumeStatSnapshot]:
    """Снимки аккаунта запроса в хронологическом порядке (старые слева — серия для
    спарклайна). `since`/`until` — границы по captured_at (`None` — без соответствующей
    границы)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 1000)
    if since is not None and until is not None:
        rows = await db.fetch(
            f"select {_STAT_COLS} from resume_stats "
            "where account_id = $1 and captured_at >= $2 and captured_at <= $3 "
            "order by captured_at asc, id asc limit $4",
            account_id,
            _aware(since),
            _aware(until),
            capped,
        )
    elif since is not None:
        rows = await db.fetch(
            f"select {_STAT_COLS} from resume_stats where account_id = $1 and captured_at >= $2 "
            "order by captured_at asc, id asc limit $3",
            account_id,
            _aware(since),
            capped,
        )
    else:
        rows = await db.fetch(
            f"select {_STAT_COLS} from resume_stats where account_id = $1 "
            "order by captured_at asc, id asc limit $2",
            account_id,
            capped,
        )
    return [ResumeStatSnapshot(**row_to_dict(r)) for r in rows]


async def list_resume_views(
    limit: int = 100, *, account_id: int, db: Executor | None = None
) -> list[ResumeView]:
    """Лента истории просмотров аккаунта запроса (свежие первыми)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 500)
    rows = await db.fetch(
        f"select {_VIEW_COLS} from resume_views where account_id = $1 "
        "order by viewed_at desc, id desc limit $2",
        account_id,
        capped,
    )
    return [ResumeView(**row_to_dict(r)) for r in rows]


__all__ = [
    "GETMATCH_PROFILE_RESUME_ID",
    "ResumeStatSnapshot",
    "ResumeView",
    "save_resume_stat",
    "save_resume_views",
    "list_resume_stats",
    "list_resume_views",
]
