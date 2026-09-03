"""Карьерная лента: DomainEvent → запись в `career_timeline`.

Чистые мапперы + тонкая запись через repo. Подписки живут в `events.py` —
издатели воронки/офферов не знают про ленту.
"""

from __future__ import annotations

from core.domains.career.models import TimelineEvent, TimelineKind
from core.domains.career.repo import insert_timeline_event
from core.kernel.events import (
    ApplicationStageChanged,
    InterviewDebriefed,
    OfferReceived,
    SearchModeChanged,
    SearchTrackChanged,
)
from core.kernel.schemas.funnel import FunnelStatus
from core.platform.db.pool import Executor

# «Просмотр» сыплется со скоринга на каждую вакансию — в ленту карьеры не тащим.
_SKIP_STAGES = frozenset({FunnelStatus.VIEWED.value})


def _source_ref_vacancy(vacancy_id: str, job_id: int | None = None) -> str:
    vid = (vacancy_id or "").strip()
    if vid:
        return vid
    if job_id is not None:
        return f"job:{job_id}"
    return ""


def _kind_for_stage(stage: str) -> TimelineKind:
    if stage == FunnelStatus.APPLIED.value:
        return "application"
    if stage == FunnelStatus.OFFER.value:
        return "offer"
    return "stage"


def _title_for_stage(stage: str, previous: str, vacancy_id: str) -> str:
    if stage == FunnelStatus.APPLIED.value:
        core = "Отклик"
    elif stage == FunnelStatus.OFFER.value:
        core = "Оффер"
    elif previous:
        core = f"{previous} → {stage}"
    else:
        core = stage
    vid = vacancy_id.strip()
    return f"{core} · {vid}" if vid else core


def timeline_from_stage_changed(evt: ApplicationStageChanged) -> TimelineEvent | None:
    """Смена этапа воронки → запись ленты. None = не пишем (шум / нет изменения)."""
    stage = (evt.stage or "").strip()
    if not stage or stage in _SKIP_STAGES:
        return None
    previous = (evt.previous_stage or "").strip()
    if previous and previous == stage:
        return None

    vacancy_id = str(evt.vacancy_id or "")
    return TimelineEvent(
        kind=_kind_for_stage(stage),
        title=_title_for_stage(stage, previous, vacancy_id),
        occurred_at=evt.occurred_at,
        payload={
            "vacancy_id": vacancy_id,
            "job_id": evt.job_id,
            "stage": stage,
            "previous_stage": previous,
            "source": evt.source or "",
            "event": evt.name,
        },
        source_ref=_source_ref_vacancy(vacancy_id, evt.job_id),
    )


def timeline_from_offer_received(evt: OfferReceived) -> TimelineEvent | None:
    vacancy_id = str(evt.vacancy_id or "")
    company = (evt.company or "").strip()
    if company:
        title = f"Оффер · {company}"
    elif vacancy_id:
        title = f"Оффер · {vacancy_id}"
    else:
        title = "Оффер"
    return TimelineEvent(
        kind="offer",
        title=title,
        occurred_at=evt.occurred_at,
        payload={
            "offer_id": str(evt.offer_id or ""),
            "vacancy_id": vacancy_id,
            "company": company,
            "status": evt.status or "",
            "event": evt.name,
        },
        source_ref=_source_ref_vacancy(vacancy_id) or str(evt.offer_id or ""),
    )


def timeline_from_interview_debriefed(evt: InterviewDebriefed) -> TimelineEvent | None:
    from core.domains.preparation.models import SIGNAL_LABELS_WEB

    vacancy_id = str(evt.vacancy_id or "")
    stage = (evt.stage or "").strip()
    signal = (evt.signal or "").strip()
    signal_label = SIGNAL_LABELS_WEB.get(signal, signal) if signal else ""
    parts = ["Разбор"]
    if stage:
        parts.append(stage)
    if signal_label:
        parts.append(signal_label)
    core = " · ".join(parts)
    title = f"{core} · {vacancy_id}" if vacancy_id else core
    return TimelineEvent(
        kind="other",
        title=title,
        occurred_at=evt.occurred_at,
        payload={
            "vacancy_id": vacancy_id,
            "stage": stage,
            "signal": signal,
            "debrief_id": evt.debrief_id,
            "event": evt.name,
        },
        source_ref=_source_ref_vacancy(vacancy_id),
    )


def timeline_from_search_mode_changed(evt: SearchModeChanged) -> TimelineEvent | None:
    """Переход режима поиска → строка ленты."""
    from core.domains.career.search_state import MODE_LABELS

    mode = (evt.mode or "").strip()
    if not mode:
        return None
    label = MODE_LABELS.get(mode, mode)  # type: ignore[arg-type]
    prev = (evt.prev_mode or "").strip()
    prev_label = MODE_LABELS.get(prev, prev) if prev else ""  # type: ignore[arg-type]
    title = f"Режим: {label}" if not prev_label else f"Режим: {prev_label} → {label}"
    return TimelineEvent(
        kind="search_mode",
        title=title,
        occurred_at=evt.occurred_at,
        payload={
            "mode": mode,
            "prev_mode": prev,
            "actor": evt.actor or "",
            "reason": evt.reason or "",
            "event": evt.name,
        },
        source_ref=f"search_mode:{mode}",
    )


def timeline_from_search_track_changed(evt: SearchTrackChanged) -> TimelineEvent | None:
    """Переход набора треков поиска → строка ленты."""
    from core.kernel.schemas.track import normalize_tracks, track_labels

    tracks = normalize_tracks(evt.tracks)
    if not tracks:
        return None
    labels = track_labels(tracks)
    prev = list(evt.prev_tracks or ())
    prev_labels = track_labels(normalize_tracks(prev)) if prev else []
    new_title = ", ".join(labels)
    title = (
        f"Трек: {new_title}"
        if not prev_labels
        else (f"Трек: {', '.join(prev_labels)} → {new_title}")
    )
    return TimelineEvent(
        kind="search_track",
        title=title,
        occurred_at=evt.occurred_at,
        payload={
            "tracks": list(tracks),
            "prev_tracks": list(prev),
            "actor": evt.actor or "",
            "reason": evt.reason or "",
            "event": evt.name,
        },
        source_ref=f"search_track:{','.join(tracks)}",
    )


async def append_timeline_event(
    event: TimelineEvent,
    *,
    account_id: int,
    db: Executor | None = None,
) -> TimelineEvent:
    """Записать готовое событие ленты (ручные job_start/promotion/… — тоже сюда)."""
    return await insert_timeline_event(event, account_id=account_id, db=db)


async def record_domain_event(
    evt: (
        ApplicationStageChanged
        | OfferReceived
        | InterviewDebriefed
        | SearchModeChanged
        | SearchTrackChanged
    ),
    *,
    db: Executor | None = None,
) -> TimelineEvent | None:
    """Смапить доменное событие и положить в ленту. None — сознательный skip.

    M5: `account_id` берём из самого события (все типы его несут) — лента пишется под
    аккаунт, который её породил, а не под владельца по умолчанию.
    """
    mapped: TimelineEvent | None
    if isinstance(evt, ApplicationStageChanged):
        mapped = timeline_from_stage_changed(evt)
    elif isinstance(evt, OfferReceived):
        mapped = timeline_from_offer_received(evt)
    elif isinstance(evt, InterviewDebriefed):
        mapped = timeline_from_interview_debriefed(evt)
    elif isinstance(evt, SearchModeChanged):
        mapped = timeline_from_search_mode_changed(evt)
    elif isinstance(evt, SearchTrackChanged):
        mapped = timeline_from_search_track_changed(evt)
    else:  # pragma: no cover — тип сужен аннотацией
        return None
    if mapped is None:
        return None
    return await append_timeline_event(mapped, account_id=evt.account_id, db=db)


__all__ = [
    "append_timeline_event",
    "record_domain_event",
    "timeline_from_interview_debriefed",
    "timeline_from_offer_received",
    "timeline_from_search_mode_changed",
    "timeline_from_search_track_changed",
    "timeline_from_stage_changed",
]
