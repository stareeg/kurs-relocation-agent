"""HH «Мои отклики» → статусы воронки Job Hunter.

Таксономия HH→воронка живёт рядом с потребителем (`core.domains.pipeline.negotiations`).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from core.kernel.schemas.funnel import (
    FunnelStatus,
    funnel_status_rank,
    resolve_funnel_status,
)


class HhNegotiationStatus(StrEnum):
    """Нормализованный статус отклика на hh.ru."""

    UNKNOWN = "unknown"
    NOT_VIEWED_BY_EMPLOYER = "not_viewed_by_employer"
    VIEWED_BY_EMPLOYER = "viewed_by_employer"
    REJECTED = "rejected"
    HH_INTERVIEW_STAGE = "hh_interview_stage"
    INVITATION = "invitation"


# API employer_state / negotiations_state id → enum
_EMPLOYER_STATE_IDS: dict[str, HhNegotiationStatus] = {
    "response": HhNegotiationStatus.NOT_VIEWED_BY_EMPLOYER,
    "consider": HhNegotiationStatus.VIEWED_BY_EMPLOYER,
    "discard": HhNegotiationStatus.REJECTED,
    "discard_by_employer": HhNegotiationStatus.REJECTED,
    "discard_after_interview": HhNegotiationStatus.REJECTED,
    "invitation": HhNegotiationStatus.INVITATION,
    "interview": HhNegotiationStatus.HH_INTERVIEW_STAGE,
    "phone_interview": HhNegotiationStatus.HH_INTERVIEW_STAGE,
    "assessment": HhNegotiationStatus.HH_INTERVIEW_STAGE,
    "hired": HhNegotiationStatus.HH_INTERVIEW_STAGE,
    "offer": HhNegotiationStatus.HH_INTERVIEW_STAGE,
}

_HH_STATUS_TEXT_PATTERNS: list[tuple[re.Pattern[str], HhNegotiationStatus]] = [
    (re.compile(r"не\s+просмотрен", re.I), HhNegotiationStatus.NOT_VIEWED_BY_EMPLOYER),
    (re.compile(r"отказ", re.I), HhNegotiationStatus.REJECTED),
    (re.compile(r"собеседован", re.I), HhNegotiationStatus.HH_INTERVIEW_STAGE),
    (re.compile(r"приглаш", re.I), HhNegotiationStatus.INVITATION),
    (re.compile(r"просмотрен", re.I), HhNegotiationStatus.VIEWED_BY_EMPLOYER),
    (re.compile(r"отклик", re.I), HhNegotiationStatus.NOT_VIEWED_BY_EMPLOYER),
]


def normalize_hh_status(
    raw: str | None,
    *,
    employer_state_id: str | None = None,
) -> HhNegotiationStatus:
    """Сырой текст HH или id employer_state → enum."""
    if employer_state_id:
        key = employer_state_id.strip().lower()
        if key in _EMPLOYER_STATE_IDS:
            return _EMPLOYER_STATE_IDS[key]

    text = (raw or "").strip().lower()
    if not text:
        return HhNegotiationStatus.UNKNOWN

    for pattern, status in _HH_STATUS_TEXT_PATTERNS:
        if pattern.search(text):
            return status

    if text in _EMPLOYER_STATE_IDS:
        return _EMPLOYER_STATE_IDS[text]

    return HhNegotiationStatus.UNKNOWN


class NegotiationMapResult(BaseModel):
    funnel_status: str
    needs_interview_tracking: bool = False
    employer_viewed: bool | None = None


def map_hh_to_funnel(
    hh_status: HhNegotiationStatus,
    *,
    has_hr_message: bool = False,
) -> NegotiationMapResult:
    """HH статус → канонический FunnelStatus (без INTERVIEW с датой)."""
    if hh_status == HhNegotiationStatus.REJECTED:
        return NegotiationMapResult(funnel_status=FunnelStatus.REJECTED)

    if hh_status == HhNegotiationStatus.HH_INTERVIEW_STAGE:
        return NegotiationMapResult(
            funnel_status=FunnelStatus.SCREENING,
            needs_interview_tracking=True,
            employer_viewed=True,
        )

    if hh_status == HhNegotiationStatus.INVITATION:
        return NegotiationMapResult(
            funnel_status=FunnelStatus.SCREENING,
            employer_viewed=True,
        )

    if hh_status == HhNegotiationStatus.VIEWED_BY_EMPLOYER:
        funnel = FunnelStatus.SCREENING if has_hr_message else FunnelStatus.APPLIED
        return NegotiationMapResult(
            funnel_status=funnel,
            employer_viewed=True,
        )

    if hh_status == HhNegotiationStatus.NOT_VIEWED_BY_EMPLOYER:
        return NegotiationMapResult(
            funnel_status=FunnelStatus.APPLIED,
            employer_viewed=False,
        )

    # unknown — минимум «Отклик»
    return NegotiationMapResult(funnel_status=FunnelStatus.APPLIED)


def is_negotiation_discrepancy(current: str | None, proposed: str) -> bool:
    """Есть расхождение HH/Job Hunter (для сортировки в UI)."""
    if not proposed or not str(proposed).strip():
        return False
    prop = resolve_funnel_status(proposed) or proposed.strip()

    if not current or not str(current).strip():
        # HH «Отказ» и то же в предложении — не «расхождение», просто нет строки в SQLite
        return prop != FunnelStatus.REJECTED

    cur = resolve_funnel_status(current) or current.strip()
    return cur != prop


def should_apply_funnel_update(
    current: str | None,
    proposed: str,
    *,
    hh_status: HhNegotiationStatus,
    force: bool = False,
    current_is_manual_rejection: bool = False,
) -> bool:
    """
    Не понижать воронку при синхронизации с HH.
    «Отказы» не навсегда — HR в Telegram может возобновить процесс.
    """
    if force:
        return True

    # Владелец сам увёл вакансию в «Отказ» (drag-and-drop на канбане, кнопка расширения, бот,
    # закрытие диалога) — авто-синк откликов не имеет права «воскрешать» её обратно в активную
    # стадию по бейджу площадки. Для такой вакансии «приглашение»/«собеседование» на hh.ru — это
    # устаревший статус, а не факт возобновления процесса: вернуть её в воронку может только сам
    # владелец (вручную). Без этого «Отказ», проставленный вручную, каждые 15 минут возвращался
    # в «Скрининг» тихим heartbeat-синком (инцидент «Толк», vacancy 89).
    if current_is_manual_rejection:
        cur = resolve_funnel_status(current) if current else None
        if cur == FunnelStatus.REJECTED and proposed != FunnelStatus.REJECTED:
            return False

    if proposed == FunnelStatus.REJECTED:
        if current == FunnelStatus.OFFER:
            return False
        # HH «Отказ» не сбрасывает активную воронку (HR-звонок и выше)
        return not (
            current and funnel_status_rank(current) >= funnel_status_rank(FunnelStatus.SCREENING)
        )

    if current == FunnelStatus.REJECTED:
        if proposed == FunnelStatus.REJECTED:
            return True
        # Возобновление после листа «Отказы»
        return funnel_status_rank(proposed) >= funnel_status_rank(FunnelStatus.APPLIED)

    if current is None or not str(current).strip():
        return True

    cur_rank = funnel_status_rank(current)
    new_rank = funnel_status_rank(proposed)

    if new_rank > cur_rank:
        return True

    if new_rank == cur_rank:
        return True

    return bool(
        proposed == FunnelStatus.APPLIED
        and current == FunnelStatus.APPLIED
        and hh_status == HhNegotiationStatus.NOT_VIEWED_BY_EMPLOYER
    )


class NegotiationSyncItem(BaseModel):
    vacancy_id: str = Field(min_length=1)
    hh_status_raw: str = ""
    hh_status: HhNegotiationStatus | None = None
    company: str = ""
    title: str = ""
    url: str = ""
    applied_at: str | None = None
    last_message: str | None = None
    employer_viewed: bool | None = None
    negotiation_id: str | None = None
    employer_state_id: str | None = None


class NegotiationSyncResultItem(BaseModel):
    vacancy_id: str
    hh_status: str
    funnel_status: str
    current_status: str | None = None
    is_discrepancy: bool = False
    applied: bool
    skipped: bool
    reason: str = ""
    needs_interview_tracking: bool = False
    llm_used: bool = False
    db_updated: int = 0


class NegotiationPreviewItem(BaseModel):
    vacancy_id: str
    funnel_status_proposed: str
    current_status: str | None = None
    is_discrepancy: bool = True
    hh_status: str = ""
    # Stub из синка откликов без JD/скора — UI просит открыть страницу вакансии.
    needs_vacancy_text: bool = False


class NegotiationsPreviewRequest(BaseModel):
    items: list[NegotiationSyncItem]


class NegotiationsPreviewResponse(BaseModel):
    items: list[NegotiationPreviewItem]


class BatchFunnelStatusRequest(BaseModel):
    vacancy_ids: list[str] = Field(default_factory=list)


class BatchFunnelStatusResponse(BaseModel):
    statuses: dict[str, str | None]


class SyncNegotiationsRequest(BaseModel):
    items: list[NegotiationSyncItem]
    source: Literal["hh_negotiations"] = "hh_negotiations"
    dry_run: bool = False
    use_llm: bool = True
    force: bool = False


class SyncNegotiationsResponse(BaseModel):
    results: list[NegotiationSyncResultItem]
    synced_count: int = 0
    skipped_count: int = 0


class SyncNegotiationsProgressEvent(BaseModel):
    """Событие NDJSON-стрима POST /funnel/sync-negotiations/stream."""

    type: Literal["start", "progress", "wait", "complete", "error"]
    total: int = 0
    done: int = 0
    synced: int = 0
    skipped: int = 0
    message: str = ""
    vacancy_id: str = ""
    quota: dict[str, int | float] | None = None
    result: NegotiationSyncResultItem | None = None
    response: SyncNegotiationsResponse | None = None


# Вакансии без активности дольше порога → «Архив» (getmatch + hh negotiations sync).
STALE_INTERACTION_DAYS = 90


def _parse_applied_at(raw: str | None) -> datetime | None:
    """applied_at из jobs/откликов: YYYY-MM-DD или YYYY-MM-DD HH:MM."""
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip().replace("T", " ")
    try:
        if len(s) >= 16:
            return datetime.strptime(s[:16], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def is_stale_interaction(
    applied_at: str | None,
    *,
    days: int = STALE_INTERACTION_DAYS,
    reference: datetime | None = None,
) -> bool:
    """Последнее взаимодействие (дата отклика) старше `days` → архив."""
    dt = _parse_applied_at(applied_at)
    if dt is None:
        return False
    ref = reference or datetime.now(UTC)
    cutoff = ref - timedelta(days=days)
    return dt.date() <= cutoff.date()
