"""Время собеседований: прошлое/будущее, статусы строк и этапов (порт interview_timing, S11).

Чистая логика без БД — нужна HR-actions (статус строки листа «Собеседования», статус этапа по
дате) и парсеру этапов (`core.domains.preparation.interview_stages.stages_from_parser`). `merge_debrief_text` дублирует
приватный `_merge_debrief_text` в `core.domains.opportunities.enrichment`
(там же используется для дозаписи дебрифа).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_MSK = timezone(timedelta(hours=3))


def ensure_msk(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=_MSK)
    return dt


def is_past_datetime(dt: datetime | None, *, now: datetime | None = None) -> bool:
    if dt is None:
        return False
    ref = now or datetime.now(tz=_MSK)
    return ensure_msk(dt) <= ensure_msk(ref)


def interview_row_status(
    scheduled_at: datetime | None,
    *,
    explicit: str | None = None,
    stage_status: str | None = None,
) -> str:
    """Статус строки листа «Собеседования»: tbd | scheduled | done."""
    if explicit in ("tbd", "scheduled", "done", "cancelled"):
        if explicit == "scheduled" and scheduled_at and is_past_datetime(scheduled_at):
            return "done"
        if explicit != "scheduled":
            return explicit
    if stage_status == "completed":
        return "done"
    if scheduled_at is None:
        return explicit or "tbd"
    if is_past_datetime(scheduled_at):
        return "done"
    return "scheduled"


def stage_status_from_datetime(
    scheduled_at: datetime | None,
    parsed_status: str | None = None,
) -> str:
    """Статус этапа в БД: scheduled | completed | cancelled | rescheduled."""
    if parsed_status in ("scheduled", "completed", "cancelled", "rescheduled"):
        if parsed_status == "scheduled" and scheduled_at and is_past_datetime(scheduled_at):
            return "completed"
        return parsed_status
    if scheduled_at and is_past_datetime(scheduled_at):
        return "completed"
    return "scheduled"


def merge_debrief_text(existing: str, new: str, *, max_len: int = 12000) -> str:
    """Дописать дебриф без дублирования блоков."""
    old = (existing or "").strip()
    add = (new or "").strip()
    if not add:
        return old[:max_len]
    if not old:
        return add[:max_len]
    if add in old:
        return old[:max_len]
    combined = f"{old}\n\n---\n{add}"
    return combined[:max_len]
