"""Доменные модели офферов + HH-таксономия откликов.

Офферы (парсинг/сравнение/торг) — ниже; HH «Мои отклики» — реэкспорт из
`hh_negotiations` (раньше `core.domains.offers.hh_negotiations`). Персист — `store.Offer`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from core.domains.offers.bonus import BonusKind, BonusType
from core.domains.offers.hh_negotiations import (
    STALE_INTERACTION_DAYS,
    BatchFunnelStatusRequest,
    BatchFunnelStatusResponse,
    HhNegotiationStatus,
    NegotiationMapResult,
    NegotiationPreviewItem,
    NegotiationsPreviewRequest,
    NegotiationsPreviewResponse,
    NegotiationSyncItem,
    NegotiationSyncResultItem,
    SyncNegotiationsProgressEvent,
    SyncNegotiationsRequest,
    SyncNegotiationsResponse,
    is_negotiation_discrepancy,
    is_stale_interaction,
    map_hh_to_funnel,
    normalize_hh_status,
    should_apply_funnel_update,
)
from core.kernel.ids import VacancyId

OfferStatus = Literal["thinking", "accepted", "declined"]
WorkFormat = Literal["remote", "hybrid", "office", "currency", "unknown"]


def _now_utc() -> datetime:
    return datetime.now(UTC)


class NegotiationArgument(BaseModel):
    """Один аргумент для торга: факт (число/сравнение) + как его сформулировать HR."""

    fact: str = Field(min_length=1, max_length=500)
    wording: str = Field(min_length=1, max_length=800)


class NegotiationBrief(BaseModel):
    """Результат RD-17 «Торг»: аргументы + черновик ответа HR. Персистится на офере,
    перечитывается при заходе — не регенерится сама по себе (cost-гард)."""

    arguments: list[NegotiationArgument] = Field(default_factory=list)
    draft_message: str = Field(default="", max_length=4000)
    generated_at: datetime = Field(default_factory=_now_utc)


class OfferRecord(BaseModel):
    """Распарсенный оффер по конкретной вакансии."""

    vacancy_id: VacancyId = Field(min_length=1)
    company: str = ""
    position: str = ""

    base_salary: int | None = Field(
        default=None,
        ge=0,
        description="Базовая ЗП gross/руб./мес (или валюта оффера) — годовая ниже",
    )
    base_salary_currency: str = "RUB"
    base_salary_period: Literal["month", "year"] = "month"
    bonus: str = Field(default="", description="Условия KPI-премии (если тип kpi выбран)")
    bonus_amount: int | None = Field(
        default=None, ge=0, description="Размер бонуса (легаси, если число)"
    )
    equity: str = Field(default="", description="Акции: права выкупа / vesting")
    signon: int | None = Field(default=None, ge=0, description="Welcome-бонус (разовая выплата)")
    vacation_days: int | None = Field(default=None, ge=0)
    notice_period: str = Field(default="", description="Срок отработки/нотис")
    start_date: datetime | None = None
    deadline: datetime | None = Field(
        default=None,
        description="Когда HR ждёт ответа на оффер",
    )
    relocation_package: str = Field(default="", description="Релокация — суммы/условия")
    work_format: WorkFormat = "unknown"
    location: str = ""
    base_salary_tax_basis: Literal["gross", "net"] = "gross"
    bonus_type: BonusType = "none"
    bonus_types: list[BonusKind] = Field(default_factory=list)
    annual_bonus_pct: int | None = Field(default=None, ge=0, le=150)
    quarterly_bonus_pct: int | None = Field(default=None, ge=0, le=150)
    bonus_monthly_equiv: int | None = Field(default=None, ge=0)
    contract_type: Literal["employment", "gph", "ip", "self_employed"] = "employment"
    location_country: str = ""

    notes: str = Field(default="", description="Свободные заметки кандидата")
    raw_text: str = Field(default="", description="Исходное письмо/сообщение оффера")

    status: OfferStatus = "thinking"
    negotiation: NegotiationBrief | None = Field(
        default=None, description="Аргументы для торга, персист, перечитывается не регенерится"
    )
    priority: int | None = Field(
        default=None,
        description="Ручной порядок для drag-n-drop в матрице, NULL = не проставлен",
    )
    office_days_per_week: int | None = Field(
        default=None, ge=0, le=7, description="Дней в офисе при гибридном формате"
    )
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)


OfferConfidence = Literal["verbal", "written", "signed"]


class OfferConfidenceInput(Protocol):
    """Минимальный набор полей для `offer_confidence` — структурно годится и `OfferRecord`,
    и облегчённым read-моделям других доменов (например, `market.pulse._Offer`) без
    конвертации строки БД в полный `OfferRecord`."""

    status: str
    raw_text: str


def offer_confidence(
    reached_offer_stage: bool, offer: OfferConfidenceInput | None
) -> OfferConfidence | None:
    """Насколько подтверждён факт «оффер»: устно / письмом / подписан.

    Не про решение кандидата (`OfferStatus` — thinking/accepted/declined уже существующего
    оффера) и не про то, доходила ли вакансия до стадии `FunnelStatus.OFFER` саму по себе —
    про то, есть ли под этим фактом хоть что-то бумажное. `reached_offer_stage` — вакансия хоть
    раз доходила до `FunnelStatus.OFFER` (история этапов воронки, не текущий статус).
    """
    if offer is not None and offer.status == "accepted":
        return "signed"
    if offer is not None and offer.raw_text.strip():
        return "written"
    if reached_offer_stage:
        return "verbal"
    return None


class OfferParseRequest(BaseModel):
    """Запрос на парсинг текста оффера."""

    text: str = Field(min_length=20, max_length=40000)
    overwrite: bool = Field(
        default=False,
        description="Перезаписать существующий оффер; иначе merge непустых полей",
    )


class OfferParseApiRequest(BaseModel):
    """Фронтовый запрос на /api/offers/parse — парсинг письма HR под оффер.

    Плоский стиль /api (vacancy_id в теле, не в path) — вместо снесённого пути
    `/vacancies/{id}/offer/parse`. Роутер переводит это в `OfferParseRequest` и зовёт
    внутренний хелпер `_offer_parse`.
    """

    vacancy_id: VacancyId = Field(min_length=1)
    text: str = Field(min_length=20, max_length=40000)
    overwrite: bool = Field(
        default=False,
        description="Перезаписать существующий оффер; иначе merge непустых полей",
    )


class OfferCreateRequest(BaseModel):
    """Создание колонки оффера под вакансию. Поля правятся инлайн через PATCH."""

    vacancy_id: VacancyId = Field(min_length=1)
    company: str = ""
    position: str = ""


class OfferReorderRequest(BaseModel):
    """Ручной порядок колонок матрицы (drag-n-drop): индекс = приоритет."""

    vacancy_ids: list[str] = Field(default_factory=list)


class OfferUpdateRequest(BaseModel):
    """Ручная правка полей оффера (кнопка «Дополнить» / инлайн-ячейка матрицы)."""

    base_salary: int | None = None
    base_salary_currency: str | None = None
    base_salary_period: Literal["month", "year"] | None = None
    bonus: str | None = None
    bonus_amount: int | None = None
    equity: str | None = None
    signon: int | None = None
    vacation_days: int | None = None
    notice_period: str | None = None
    start_date: datetime | None = None
    deadline: datetime | None = None
    relocation_package: str | None = None
    work_format: WorkFormat | None = None
    location: str | None = None
    base_salary_tax_basis: Literal["gross", "net"] | None = None
    bonus_type: BonusType | None = None
    bonus_types: list[BonusKind] | None = None
    annual_bonus_pct: int | None = None
    quarterly_bonus_pct: int | None = None
    bonus_monthly_equiv: int | None = None
    contract_type: Literal["employment", "gph", "ip", "self_employed"] | None = None
    location_country: str | None = None
    notes: str | None = None
    status: OfferStatus | None = None
    priority: int | None = None
    office_days_per_week: int | None = Field(default=None, ge=0, le=7)


class OfferProsCons(BaseModel):
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)


class OfferRanking(BaseModel):
    rank: int = Field(ge=1)
    vacancy_id: VacancyId
    company: str = ""
    position: str = ""
    summary: str = ""
    pros_cons: OfferProsCons = Field(default_factory=OfferProsCons)


class OfferSensitivity(BaseModel):
    """Что изменилось бы, если бы условие X стало Y."""

    scenario: str = Field(min_length=1, max_length=500)
    impact: str = Field(min_length=1, max_length=1000)
    affected_vacancy_id: str = ""


class OfferComparison(BaseModel):
    """Результат LLM-сравнения нескольких офферов под приоритеты кандидата."""

    rankings: list[OfferRanking] = Field(default_factory=list)
    sensitivity: list[OfferSensitivity] = Field(default_factory=list)
    recommendation: str = Field(default="", max_length=4000)
    markdown: str = Field(default="", description="Готовый Markdown для Telegram/файла")
    favorable_fields: dict[str, list[str]] = Field(
        default_factory=dict,
        description="vacancy_id → список ключей полей (как во фронтовом RowDef.key), "
        "которые LLM считает более выгодными у этого оффера",
    )
    compared_at: datetime = Field(default_factory=_now_utc)


class OfferCompareRequest(BaseModel):
    """Опциональный запрос на /decide — фильтры по списку оффер-кандидатов."""

    vacancy_ids: list[str] = Field(default_factory=list)
    max_age_days: int = Field(default=30, ge=1, le=180)
    save_to_disk: bool = False


class OfferCompareResponse(BaseModel):
    offers: list[OfferRecord]
    comparison: OfferComparison | None = None
    detail: str = ""


class OfferNegotiateResponse(BaseModel):
    offer: OfferRecord
    negotiation: NegotiationBrief


__all__ = [
    "BatchFunnelStatusRequest",
    "BatchFunnelStatusResponse",
    "HhNegotiationStatus",
    "NegotiationArgument",
    "NegotiationBrief",
    "NegotiationMapResult",
    "NegotiationPreviewItem",
    "NegotiationSyncItem",
    "NegotiationSyncResultItem",
    "NegotiationsPreviewRequest",
    "NegotiationsPreviewResponse",
    "OfferComparison",
    "OfferConfidence",
    "OfferConfidenceInput",
    "OfferCompareRequest",
    "OfferCompareResponse",
    "OfferCreateRequest",
    "OfferNegotiateResponse",
    "OfferParseApiRequest",
    "OfferParseRequest",
    "OfferProsCons",
    "OfferRanking",
    "OfferRecord",
    "OfferReorderRequest",
    "OfferSensitivity",
    "OfferStatus",
    "OfferUpdateRequest",
    "STALE_INTERACTION_DAYS",
    "SyncNegotiationsProgressEvent",
    "SyncNegotiationsRequest",
    "SyncNegotiationsResponse",
    "WorkFormat",
    "is_negotiation_discrepancy",
    "is_stale_interaction",
    "map_hh_to_funnel",
    "normalize_hh_status",
    "offer_confidence",
    "should_apply_funnel_update",
]
