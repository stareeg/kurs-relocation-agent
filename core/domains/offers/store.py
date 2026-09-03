"""Персистентность офферов per vacancy_id (Postgres, таблица `offers`).

Только хранение: LLM-парсер письма (`offer_parser`), сравнение (`offer_compare`) и торг
(`offer_negotiation`) — чистая логика без БД, рядом в домене.

`upsert_offer(merge=True)` мержит непустые поля поверх существующих (пустое = None/""/0),
`created_at` иммутабелен после создания, `updated_at` освежается всегда.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from core.domains.offers.bonus import apply_bonus_patch, offer_bonus_types
from core.domains.offers.events import publish_offer_received
from core.domains.offers.models import OfferComparison
from core.kernel.ids import VacancyId
from core.platform.db.pool import Executor, get_pool, row_to_dict

_COLUMNS = (
    "vacancy_id, company, position, base_salary, base_salary_currency, base_salary_period, "
    "bonus, bonus_amount, equity, signon, vacation_days, notice_period, start_date, deadline, "
    "relocation_package, work_format, location, notes, raw_text, status, negotiation, "
    "negotiation_generated_at, priority, office_days_per_week, base_salary_tax_basis, "
    "bonus_type, bonus_types, annual_bonus_pct, quarterly_bonus_pct, "
    "bonus_monthly_equiv, bonus_monthly_equiv_source_hash, contract_type, "
    "location_country, created_at, updated_at"
)
# Колонки, которые НЕ затираем при on conflict: vacancy_id — ключ, created_at — иммутабелен.
_IMMUTABLE_ON_UPDATE = {"vacancy_id", "created_at"}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """Naive datetime → UTC-aware (timestamptz).

    Парсер даёт aware (MSK), ручная правка может naive.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class Offer(BaseModel):
    """Оффер по вакансии. Допустимые значения enum-полей валидирует CHECK в миграции 0064:

    base_salary_period: month | year
    work_format:        remote | hybrid | office | currency | unknown
    status:             thinking | accepted | declined

    ``vacancy_id`` — типизированный ``VacancyId``; в JSON/БД это по-прежнему str.
    """

    vacancy_id: VacancyId
    company: str = ""
    position: str = ""
    base_salary: int | None = None
    base_salary_currency: str = "RUB"
    base_salary_period: str = "month"
    bonus: str = ""
    bonus_amount: int | None = None
    equity: str = ""
    signon: int | None = None
    vacation_days: int | None = None
    notice_period: str = ""
    start_date: datetime | None = None
    deadline: datetime | None = None
    relocation_package: str = ""
    work_format: str = "unknown"
    location: str = ""
    notes: str = ""
    raw_text: str = ""
    status: str = "thinking"
    negotiation: dict[str, Any] | None = None
    negotiation_generated_at: datetime | None = None
    priority: int | None = None
    office_days_per_week: int | None = None
    base_salary_tax_basis: str = "gross"
    bonus_type: str = "none"
    bonus_types: list[str] = Field(default_factory=list)
    annual_bonus_pct: int | None = None
    quarterly_bonus_pct: int | None = None
    bonus_monthly_equiv: int | None = None
    bonus_monthly_equiv_source_hash: str = ""
    contract_type: str = "employment"
    location_country: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


# Поля, которые при merge считаем «пустыми» по значению (None/""/0 не затирают
# заполненное). created_at/updated_at в мерже не участвуют — их выставляет upsert; negotiation —
# отдельный write-path (`save_offer_negotiation`), обычный merge/upsert его не трогает.
_MERGE_SKIP = {"created_at", "updated_at", "negotiation", "negotiation_generated_at"}


def _merge_offer(existing: Offer, incoming: Offer) -> Offer:
    """Мерж непустых полей incoming поверх existing (`upsert_offer(merge=True)`).

    Пустое значение (None/""/0) не затирает заполненное; vacancy_id пустым не перезаписываем.
    """
    merged = existing.model_dump()
    for key, value in incoming.model_dump().items():
        if key in _MERGE_SKIP:
            continue
        empty = value in (None, "", 0) or value == []
        if empty:
            if key == "vacancy_id":
                continue
            existing_val = merged.get(key)
            if existing_val not in (None, "", 0) and existing_val != []:
                continue
        merged[key] = value
    return Offer(**merged)


async def load_offer(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> Offer | None:
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_COLUMNS} from offers where account_id = $1 and vacancy_id = $2",
        account_id,
        vacancy_id,
    )
    return Offer(**row_to_dict(row)) if row else None


async def upsert_offer(
    offer: Offer, *, account_id: int, merge: bool = True, db: Executor | None = None
) -> Offer:
    """Сохранить оффер. merge=True — непустые поля поверх существующего; merge=False — перезапись.

    created_at иммутабелен (на conflict сохраняется исходный), updated_at всегда = now.
    """
    if not offer.vacancy_id:
        raise ValueError("vacancy_id required")
    db = db or get_pool()
    now = _now()
    existing = await load_offer(offer.vacancy_id, account_id=account_id, db=db)
    record = _merge_offer(existing, offer) if (existing and merge) else offer
    record = record.model_copy(
        update=apply_bonus_patch(
            {
                "bonus_types": offer_bonus_types(record.bonus_types, record.bonus_type),
                "annual_bonus_pct": record.annual_bonus_pct,
                "quarterly_bonus_pct": record.quarterly_bonus_pct,
            }
        )
    )
    created_at = existing.created_at if existing else now
    # «Старт» = момент появления оффера (вход в статус), не ручная дата выхода.
    if record.start_date is None and existing is None:
        record = record.model_copy(update={"start_date": created_at})
    elif record.start_date is None and existing is not None and existing.start_date is None:
        record = record.model_copy(update={"start_date": existing.created_at or created_at})

    params: list[Any] = [
        account_id,
        record.vacancy_id,
        record.company,
        record.position,
        record.base_salary,
        record.base_salary_currency,
        record.base_salary_period,
        record.bonus,
        record.bonus_amount,
        record.equity,
        record.signon,
        record.vacation_days,
        record.notice_period,
        _aware(record.start_date),
        _aware(record.deadline),
        record.relocation_package,
        record.work_format,
        record.location,
        record.notes,
        record.raw_text,
        record.status,
        record.negotiation,
        _aware(record.negotiation_generated_at),
        record.priority,
        record.office_days_per_week,
        record.base_salary_tax_basis,
        record.bonus_type,
        record.bonus_types,
        record.annual_bonus_pct,
        record.quarterly_bonus_pct,
        record.bonus_monthly_equiv,
        record.bonus_monthly_equiv_source_hash,
        record.contract_type,
        record.location_country,
        created_at,
        now,
    ]
    update_set = ", ".join(
        f"{c} = excluded.{c}" for c in _COLUMNS.split(", ") if c not in _IMMUTABLE_ON_UPDATE
    )
    placeholders = ", ".join(f"${i}" for i in range(1, len(params) + 1))
    row = await db.fetchrow(
        f"insert into offers (account_id, {_COLUMNS}) values ({placeholders}) "
        f"on conflict (account_id, vacancy_id) do update set {update_set} "
        f"returning {_COLUMNS}",
        *params,
    )
    assert row is not None  # insert ... returning всегда отдаёт строку
    saved = Offer(**row_to_dict(row))

    # A-11: событие — про появление оффера, а не про каждую правку полей.
    if existing is None:
        publish_offer_received(
            vacancy_id=saved.vacancy_id,
            account_id=account_id,
            company=saved.company,
            status=saved.status,
        )
    return saved


async def load_active_offers(
    *,
    account_id: int,
    max_age_days: int = 30,
    statuses: tuple[str, ...] = ("thinking", "accepted"),
    db: Executor | None = None,
) -> list[Offer]:
    """Активные офферы для /offers/decide: статус из набора и свежее max_age_days по updated_at."""
    db = db or get_pool()
    if max_age_days <= 0:
        max_age_days = 30
    rows = await db.fetch(
        f"select {_COLUMNS} from offers "
        f"where account_id = $1 and status = any($2::text[]) "
        f"and updated_at >= now() - make_interval(days => $3) "
        f"order by updated_at desc",
        account_id,
        list(statuses),
        max_age_days,
    )
    return [Offer(**row_to_dict(r)) for r in rows]


async def load_offers_by_ids(
    vacancy_ids: list[str], *, account_id: int, db: Executor | None = None
) -> list[Offer]:
    ids = [v for v in vacancy_ids if v]
    if not ids:
        return []
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_COLUMNS} from offers where account_id = $1 and vacancy_id = any($2)",
        account_id,
        ids,
    )
    return [Offer(**row_to_dict(r)) for r in rows]


async def load_all_offers(
    *, account_id: int, limit: int = 100, db: Executor | None = None
) -> list[Offer]:
    """Все офферы аккаунта для матрицы сравнения веба (свежие первыми, приоритетные первее
    всех). UI-6, OF-2.

    В отличие от load_active_offers — без фильтра по статусу/возрасту: матрица показывает и
    accepted/declined со статус-чипом. `priority` (ручной drag-n-drop) впереди —
    непроставленные (NULL) уходят в хвост в прежнем порядке по `updated_at`.
    """
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_COLUMNS} from offers "
        f"where account_id = $1 "
        f"order by coalesce(priority, 999999), updated_at desc limit $2",
        account_id,
        limit,
    )
    return [Offer(**row_to_dict(r)) for r in rows]


async def reorder_offers(
    order: list[str], *, account_id: int, db: Executor | None = None
) -> list[Offer]:
    """Проставить ручной приоритет (drag-n-drop в матрице): индекс в `order` = приоритет,

    начиная с 1. Неизвестные vacancy_id молча пропускаются (0 affected rows) — фронт шлёт весь
    список колонок разом, гонка с параллельным DELETE не должна валить весь reorder.
    """
    ids = [v for v in order if v]
    if not ids:
        return []
    db = db or get_pool()
    await db.executemany(
        "update offers set priority = $3, updated_at = now() "
        "where account_id = $1 and vacancy_id = $2",
        [(account_id, vacancy_id, idx) for idx, vacancy_id in enumerate(ids, start=1)],
    )
    loaded = {
        str(o.vacancy_id): o for o in await load_offers_by_ids(ids, account_id=account_id, db=db)
    }
    return [loaded[vacancy_id] for vacancy_id in ids if vacancy_id in loaded]


async def delete_offer(vacancy_id: str, *, account_id: int, db: Executor | None = None) -> bool:
    """Удалить оффер (убрать колонку из матрицы). True — строка была."""
    if not vacancy_id:
        return False
    db = db or get_pool()
    row = await db.fetchrow(
        "delete from offers where account_id = $1 and vacancy_id = $2 returning vacancy_id",
        account_id,
        vacancy_id,
    )
    return row is not None


async def save_offer_negotiation(
    vacancy_id: str, negotiation: dict[str, Any], *, account_id: int, db: Executor | None = None
) -> Offer | None:
    """Персист брифа торга. Отдельный write-path от `upsert_offer` — не трогает
    updated_at/остальные поля оффера, только сам бриф + отметку времени генерации."""
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        f"update offers set negotiation = $3, negotiation_generated_at = now() "
        f"where account_id = $1 and vacancy_id = $2 returning {_COLUMNS}",
        account_id,
        vacancy_id,
        negotiation,
    )
    return Offer(**row_to_dict(row)) if row else None


async def save_offer_bonus_estimate(
    vacancy_id: str,
    bonus_monthly_equiv: int | None,
    source_hash: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> Offer | None:
    """Персист расчёта помесячного эквивалента премии. Отдельный write-path — не трогает
    updated_at/остальные поля оффера, только сам расчёт + хэш входов, по которому он посчитан."""
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        f"update offers set bonus_monthly_equiv = $3, bonus_monthly_equiv_source_hash = $4 "
        f"where account_id = $1 and vacancy_id = $2 returning {_COLUMNS}",
        account_id,
        vacancy_id,
        bonus_monthly_equiv,
        source_hash,
    )
    return Offer(**row_to_dict(row)) if row else None


async def load_offer_comparison_cache(
    vacancy_ids_hash: str, *, account_id: int, db: Executor | None = None
) -> OfferComparison | None:
    """Прочитать закэшированный результат автосравнения по хэшу состава+состояния офферов."""
    if not vacancy_ids_hash:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        "select comparison from offer_comparisons_cache "
        "where account_id = $1 and vacancy_ids_hash = $2",
        account_id,
        vacancy_ids_hash,
    )
    return OfferComparison.model_validate(row["comparison"]) if row else None


async def save_offer_comparison_cache(
    vacancy_ids_hash: str,
    comparison: OfferComparison,
    *,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Сохранить результат автосравнения под хэшем набора — следующий вызов с тем же
    состоянием офферов отдаётся из кэша, не бьёт по деньгам повторным LLM-вызовом."""
    if not vacancy_ids_hash:
        return
    db = db or get_pool()
    await db.execute(
        "insert into offer_comparisons_cache (account_id, vacancy_ids_hash, comparison) "
        "values ($1, $2, $3) "
        "on conflict (account_id, vacancy_ids_hash) do update set "
        "comparison = excluded.comparison, computed_at = now()",
        account_id,
        vacancy_ids_hash,
        comparison.model_dump(mode="json"),
    )
