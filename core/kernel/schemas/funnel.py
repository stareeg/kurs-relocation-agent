"""Единый источник статусов воронки для веба, бота и расширения.

«Архив» — легаси-значение колонки «Воронка»; при чтении сводится к «Отказ»
(`resolve_funnel_status`). Новые записи в «Архив» не пишем.

Потребители таксономии: `core.domains.pipeline.funnel_sync` / `negotiations`, api, бот,
расширение.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FunnelStatus(StrEnum):
    """Статус воронки — колонка «Воронка»; одна строка = один лист из шести."""

    VIEWED = "Просмотр"
    APPLIED = "Отклик"
    REJECTED = "Отказ"
    SCREENING = "Скрининг"
    TECH = "Техничка"
    FINAL = "Финал"
    OFFER = "Оффер"
    ARCHIVE = "Архив"


# Маппинг intent HR-сообщения → статус воронки (бот).
INTENT_TO_FUNNEL_STATUS: dict[str, str] = {
    "interview_scheduled": FunnelStatus.SCREENING,
    "interview_rescheduled": FunnelStatus.SCREENING,
    "scheduling_request": FunnelStatus.SCREENING,
    "rejection": FunnelStatus.REJECTED,
    "offer": FunnelStatus.OFFER,
    "test_task": FunnelStatus.TECH,
    "follow_up": FunnelStatus.SCREENING,
    "hr_outreach": FunnelStatus.SCREENING,
    "general": FunnelStatus.SCREENING,
}

DEFAULT_FUNNEL_STATUS = FunnelStatus.VIEWED

# Активные этапы (не «Просмотр» / «Отказ») — перенос с листа «Просмотры».
ENGAGED_FUNNEL_STATUSES: frozenset[str] = frozenset(
    {
        FunnelStatus.APPLIED,
        FunnelStatus.SCREENING,
        FunnelStatus.TECH,
        FunnelStatus.FINAL,
        FunnelStatus.OFFER,
    }
)


def is_engaged_status(status: str) -> bool:
    resolved = resolve_funnel_status(status) or (status or "").strip()
    return resolved in ENGAGED_FUNNEL_STATUSES


def has_responded_status(status: str | None) -> bool:
    """Владелец принял решение вовлечься — любой статус кроме дефолтного «Просмотр».

    Отличие от `is_engaged_status`: та НЕ считает `REJECTED` вовлечённым (это терминал),
    здесь же `REJECTED` — «откликнулся» (отказ HR приходит ПОСЛЕ отклика — отдельного статуса
    «отказали до отклика» в этом продукте нет). Используется отчётами по решениям владельца
    (Этап 7 §7.2/7.4, plans/scoring_precision_2026_08_17.md) — не путать с воронкой/канбаном.
    """
    resolved = resolve_funnel_status(status) or (status or "").strip()
    return bool(resolved) and resolved != FunnelStatus.VIEWED.value


FUNNEL_STATUS_RANK: dict[str, int] = {
    FunnelStatus.VIEWED: 0,
    FunnelStatus.APPLIED: 10,
    FunnelStatus.SCREENING: 30,
    FunnelStatus.TECH: 50,
    FunnelStatus.FINAL: 60,
    FunnelStatus.OFFER: 70,
    FunnelStatus.REJECTED: -10,
    FunnelStatus.ARCHIVE: -20,
}

FUNNEL_STAGE_NUMBER: dict[str, int] = {
    FunnelStatus.VIEWED: 1,
    FunnelStatus.APPLIED: 2,
    FunnelStatus.SCREENING: 3,
    FunnelStatus.TECH: 4,
    FunnelStatus.FINAL: 5,
    FunnelStatus.OFFER: 6,
    FunnelStatus.REJECTED: 0,
    FunnelStatus.ARCHIVE: 0,
}


def funnel_status_rank(status: str | None) -> int:
    if not status or not str(status).strip():
        return -1
    resolved = resolve_funnel_status(status) or status.strip()
    return FUNNEL_STATUS_RANK.get(resolved, 5)


def funnel_stage_number(status: str | None) -> int | str:
    """Метка максимального этапа воронки."""
    if not status or not str(status).strip():
        return ""
    resolved = resolve_funnel_status(status) or status.strip()
    return FUNNEL_STAGE_NUMBER.get(resolved, "")


FUNNEL_STATUS_ALIASES: dict[str, str] = {
    "просмотрено": FunnelStatus.VIEWED,
    "просмотр": FunnelStatus.VIEWED,
    "откликнулись": FunnelStatus.APPLIED,
    "отклик": FunnelStatus.APPLIED,
    "отказ": FunnelStatus.REJECTED,
    "скрининг": FunnelStatus.SCREENING,
    "собеседование": FunnelStatus.SCREENING,
    "собеседование (уточняется)": FunnelStatus.SCREENING,
    "hr inbound": FunnelStatus.SCREENING,
    "в переписке": FunnelStatus.SCREENING,
    "в переписке с hr": FunnelStatus.SCREENING,
    "переписка с hr": FunnelStatus.SCREENING,
    "hr-звонок": FunnelStatus.SCREENING,
    "звонок": FunnelStatus.SCREENING,
    "созвон": FunnelStatus.SCREENING,
    "техничка": FunnelStatus.TECH,
    "техинтервью": FunnelStatus.TECH,
    "техническое интервью": FunnelStatus.TECH,
    "тестовое": FunnelStatus.TECH,
    "тестовое задание": FunnelStatus.TECH,
    "финал": FunnelStatus.FINAL,
    "финальное собеседование": FunnelStatus.FINAL,
    "финальный раунд": FunnelStatus.FINAL,
    "финальный этап": FunnelStatus.FINAL,
    "оффер": FunnelStatus.OFFER,
    "offer": FunnelStatus.OFFER,
    # «Архив» больше не пишем как статус воронки — легаси-строки сводим к «Отказ».
    "архив": FunnelStatus.REJECTED,
    "в архиве": FunnelStatus.REJECTED,
    "vacancy in archive": FunnelStatus.REJECTED,
}


def all_funnel_status_values() -> list[str]:
    return [s.value for s in FunnelStatus]


def resolve_funnel_status(
    raw: str | None,
    intent: str | None = None,
) -> str | None:
    """Привести строку/intent к каноническому FunnelStatus.value.

    Легаси «Архив» нормализуем в «Отказ» — отдельной колонки/стадии воронки больше нет.
    """
    if raw:
        text = raw.strip()
        if not text:
            pass
        else:
            lower = text.lower()
            for status in FunnelStatus:
                if lower == status.value.lower():
                    if status is FunnelStatus.ARCHIVE:
                        return FunnelStatus.REJECTED.value
                    return status.value
            if lower in FUNNEL_STATUS_ALIASES:
                return FUNNEL_STATUS_ALIASES[lower]

    if intent and intent in INTENT_TO_FUNNEL_STATUS:
        return INTENT_TO_FUNNEL_STATUS[intent]
    return None


class FunnelStatusUpdate(BaseModel):
    vacancy_id: str = Field(min_length=1)
    status: FunnelStatus
    cover_letter: str | None = Field(
        default=None,
        description="Текст сопроводительного после отклика на HH",
    )
    published_at: str | None = Field(
        default=None,
        description="Дата публикации вакансии (если ещё не записана)",
    )
    offer_at: str | None = Field(
        default=None,
        description="Дата оффера (YYYY-MM-DD HH:MM)",
    )


class FunnelStatusResponse(BaseModel):
    vacancy_id: str
    status: str | None = None
    source: Literal["db", "sheets"] | None = None
    sheets_synced: bool | None = None
    sheets_error: str | None = None
    skipped: bool = False
