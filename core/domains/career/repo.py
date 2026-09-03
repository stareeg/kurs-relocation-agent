"""Доступ к таблицам career. CRUD без роутеров/UI.

M5 (plans/multitenancy_gaps_2026_08_06.md §2/§6): все таблицы аккаунт-скоуп — каждая функция
принимает обязательный `account_id`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.domains.career.models import CareerFact, PortfolioItem, TimelineEvent
from core.platform.db.pool import Executor, get_pool, row_to_dict

_PORTFOLIO_COLS = (
    "id, project, role, outcome, artifact_url, source_ref, notes, created_at, updated_at"
)
_TIMELINE_COLS = "id, kind, title, occurred_at, payload, source_ref, created_at"
_FACT_COLS = (
    "id, fact, fact_type, source_kind, source_ref, confidence, recorded_at, "
    "expires_at, payload, created_at"
)


def timeline_from_row(row: Any) -> TimelineEvent:
    return TimelineEvent(**row_to_dict(row))


async def insert_portfolio_item(
    item: PortfolioItem, *, account_id: int, db: Executor | None = None
) -> PortfolioItem:
    """Идемпотентно по `source_ref` (0152): повторный черновик по тому же резюме-блоку/
    разбору/офферу не создаёт вторую карточку — возвращает уже существующую."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into career_portfolio_items "
        "(account_id, project, role, outcome, artifact_url, source_ref, notes) "
        f"values ($1, $2, $3, $4, $5, $6, $7) "
        "on conflict (account_id, source_ref) where source_ref <> '' do nothing "
        f"returning {_PORTFOLIO_COLS}",
        account_id,
        item.project.strip(),
        item.role,
        item.outcome,
        item.artifact_url,
        item.source_ref,
        item.notes,
    )
    if row is None:
        row = await db.fetchrow(
            f"select {_PORTFOLIO_COLS} from career_portfolio_items "
            "where account_id = $1 and source_ref = $2",
            account_id,
            item.source_ref,
        )
    assert row is not None
    return PortfolioItem(**row_to_dict(row))


async def delete_portfolio_item(
    item_id: int, *, account_id: int, db: Executor | None = None
) -> bool:
    """Удалить элемент портфолио (Этап 5.0 редизайна «Карьеры») — например, неверный
    авто-черновик из разбора/оффера (5.2). True — строка была (и принадлежала аккаунту)."""
    db = db or get_pool()
    result = await db.execute(
        "delete from career_portfolio_items where id = $1 and account_id = $2",
        item_id,
        account_id,
    )
    return str(result).rsplit(" ", 1)[-1] not in ("", "0")


async def list_portfolio_items(
    *, account_id: int, db: Executor | None = None
) -> list[PortfolioItem]:
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_PORTFOLIO_COLS} from career_portfolio_items where account_id = $1 "
        "order by updated_at desc, id desc",
        account_id,
    )
    return [PortfolioItem(**row_to_dict(r)) for r in rows]


async def insert_timeline_event(
    event: TimelineEvent, *, account_id: int, db: Executor | None = None
) -> TimelineEvent:
    """Идемпотентно для `kind="offer"` по `source_ref` (0152): повторная публикация
    `OfferReceived` для той же вакансии не создаёт вторую строку ленты — возвращает уже
    существующую. Другие `kind` не защищены — см. план, «Осознанно НЕ делаем в этом заходе»
    (там `source_ref` законно повторяется между разными occurrence)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into career_timeline "
        "(account_id, kind, title, occurred_at, payload, source_ref) "
        f"values ($1, $2, $3, coalesce($4, now()), $5, $6) "
        "on conflict (account_id, source_ref) where kind = 'offer' and source_ref <> '' "
        f"do nothing returning {_TIMELINE_COLS}",
        account_id,
        event.kind,
        event.title.strip(),
        event.occurred_at,
        event.payload,
        event.source_ref,
    )
    if row is None:
        row = await db.fetchrow(
            f"select {_TIMELINE_COLS} from career_timeline "
            "where account_id = $1 and kind = $2 and source_ref = $3",
            account_id,
            event.kind,
            event.source_ref,
        )
    assert row is not None
    return timeline_from_row(row)


async def list_timeline_events(
    *,
    account_id: int,
    limit: int = 100,
    kinds: list[str] | None = None,
    before_id: int | None = None,
    db: Executor | None = None,
) -> list[TimelineEvent]:
    """Свежие первыми (`occurred_at desc, id desc`). `before_id` — курсор «Показать ещё»
    (Этап 2.4 плана редизайна «Карьеры»): продолжает тот же порядок с элемента, идущего
    сразу за строкой `before_id`, а не с абсолютной даты — работает и для ручных вех с
    произвольным `occurred_at`."""
    db = db or get_pool()
    conditions = ["account_id = $1"]
    params: list[Any] = [account_id]
    if kinds is not None:
        params.append(kinds)
        conditions.append(f"kind = any(${len(params)}::text[])")
    if before_id is not None:
        params.append(before_id)
        conditions.append(
            f"(occurred_at, id) < (select occurred_at, id from career_timeline "
            f"where id = ${len(params)} and account_id = $1)"
        )
    params.append(limit)
    where = " and ".join(conditions)
    rows = await db.fetch(
        f"select {_TIMELINE_COLS} from career_timeline where {where} "
        f"order by occurred_at desc, id desc limit ${len(params)}",
        *params,
    )
    return [timeline_from_row(r) for r in rows]


def fact_from_row(row: Any) -> CareerFact:
    return CareerFact(**row_to_dict(row))


async def insert_fact(
    fact: CareerFact, *, account_id: int, db: Executor | None = None
) -> CareerFact:
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into career_facts "
        "(account_id, fact, fact_type, source_kind, source_ref, confidence, recorded_at, "
        "expires_at, payload) "
        f"values ($1, $2, $3, $4, $5, $6, coalesce($7, now()), $8, $9) "
        f"returning {_FACT_COLS}",
        account_id,
        fact.fact.strip(),
        fact.fact_type,
        fact.source_kind,
        fact.source_ref,
        fact.confidence,
        fact.recorded_at,
        fact.expires_at,
        fact.payload,
    )
    assert row is not None
    return fact_from_row(row)


async def merge_fact(
    fact_id: int,
    *,
    account_id: int,
    fact: str,
    confidence: float,
    source_ref: str,
    recorded_at: datetime | None,
    expires_at: datetime | None,
    payload: dict[str, Any],
    db: Executor | None = None,
) -> CareerFact:
    """Обновить уже существующий факт свежим извлечением вместо новой строки (Этап 4.1
    редизайна «Карьеры»): текст/уверенность/источник/срок годности/payload перезаписываются
    данными нового разбора, `id`/`created_at` не трогаем — история остаётся одной карточкой."""
    db = db or get_pool()
    row = await db.fetchrow(
        "update career_facts set fact = $3, confidence = $4, source_ref = $5, "
        "recorded_at = coalesce($6, recorded_at), expires_at = $7, payload = $8 "
        "where id = $1 and account_id = $2 "
        f"returning {_FACT_COLS}",
        fact_id,
        account_id,
        fact.strip(),
        confidence,
        source_ref,
        recorded_at,
        expires_at,
        payload,
    )
    assert row is not None
    return fact_from_row(row)


async def list_active_facts(
    *,
    account_id: int,
    limit: int = 30,
    source_kind: str | None = None,
    fact_type: str | None = None,
    db: Executor | None = None,
) -> list[CareerFact]:
    """Активные факты аккаунта: не протухшие (`expires_at` null или в будущем)."""
    db = db or get_pool()
    capped = min(max(limit, 1), 200)
    conditions = ["account_id = $1", "(expires_at is null or expires_at > now())"]
    params: list[Any] = [account_id]
    if source_kind is not None:
        params.append(source_kind)
        conditions.append(f"source_kind = ${len(params)}")
    if fact_type is not None:
        params.append(fact_type)
        conditions.append(f"fact_type = ${len(params)}")
    params.append(capped)
    where = " and ".join(conditions)
    rows = await db.fetch(
        f"select {_FACT_COLS} from career_facts where {where} "
        f"order by recorded_at desc, id desc limit ${len(params)}",
        *params,
    )
    return [fact_from_row(r) for r in rows]


async def get_fact(
    fact_id: int, *, account_id: int, db: Executor | None = None
) -> CareerFact | None:
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_FACT_COLS} from career_facts where id = $1 and account_id = $2",
        fact_id,
        account_id,
    )
    return fact_from_row(row) if row is not None else None


async def update_fact(
    fact_id: int,
    *,
    account_id: int,
    fact: str | None = None,
    pinned: bool | None = None,
    db: Executor | None = None,
) -> CareerFact | None:
    """Правка текста и/или закрепление (`pinned=True` → `expires_at = null`, бессрочно).

    `pinned` не `True` — срок не трогаем (снять закрепление этой ручкой нельзя, см. план Э9.4).
    Нет факта/чужой → None.
    """
    current = await get_fact(fact_id, account_id=account_id, db=db)
    if current is None:
        return None
    db = db or get_pool()
    next_fact = fact.strip() if fact is not None else current.fact
    next_expires = None if pinned else current.expires_at
    row = await db.fetchrow(
        "update career_facts set fact = $3, expires_at = $4 "
        "where id = $1 and account_id = $2 "
        f"returning {_FACT_COLS}",
        fact_id,
        account_id,
        next_fact,
        next_expires,
    )
    assert row is not None
    return fact_from_row(row)


async def delete_fact(fact_id: int, *, account_id: int, db: Executor | None = None) -> bool:
    """Удалить факт. True — строка была (и принадлежала аккаунту)."""
    db = db or get_pool()
    result = await db.execute(
        "delete from career_facts where id = $1 and account_id = $2", fact_id, account_id
    )
    return str(result).rsplit(" ", 1)[-1] not in ("", "0")


async def count_facts_since(
    cutoff: datetime, *, account_id: int, db: Executor | None = None
) -> int:
    """Сколько фактов записано с `cutoff` (для дельты «Что изменилось», Э9.5)."""
    db = db or get_pool()
    return int(
        await db.fetchval(
            "select count(*) from career_facts where account_id = $1 and recorded_at >= $2",
            account_id,
            cutoff,
        )
    )


async def count_timeline_events_since(
    cutoff: datetime, *, account_id: int, db: Executor | None = None
) -> int:
    """Сколько событий ленты произошло с `cutoff` (для дельты «Что изменилось», Э9.5)."""
    db = db or get_pool()
    return int(
        await db.fetchval(
            "select count(*) from career_timeline where account_id = $1 and occurred_at >= $2",
            account_id,
            cutoff,
        )
    )


__all__ = [
    "count_facts_since",
    "count_timeline_events_since",
    "delete_fact",
    "delete_portfolio_item",
    "fact_from_row",
    "get_fact",
    "insert_fact",
    "insert_portfolio_item",
    "insert_timeline_event",
    "list_active_facts",
    "list_portfolio_items",
    "list_timeline_events",
    "merge_fact",
    "timeline_from_row",
    "update_fact",
]
