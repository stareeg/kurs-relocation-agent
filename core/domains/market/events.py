"""События домена market: что публикует и на что подписан (шина — A-11).

L-26: дирти-трекер снапшотов (`snapshot_dirty.py`) слушает события, реально меняющие вход
grid/pulse/search агрегатов, — так плановый пересчёт (`snapshot_refresh.py`) считает только
затронутые срезы вместо всех на каждый тик.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.domains.market import snapshot_dirty
from core.kernel.events import (
    ApplicationStageChanged,
    HrMessageReceived,
    OfferReceived,
    ResumeUpdated,
    SearchTrackChanged,
    VacancyScored,
)

PUBLISHES: tuple[type, ...] = ()


def on_vacancy_scored(_evt: VacancyScored) -> None:
    """Новая/переоценённая вакансия — вход KPI и воронки (grid/pulse/search)."""
    snapshot_dirty.mark_dirty(snapshot_dirty.GRID, snapshot_dirty.PULSE, snapshot_dirty.SEARCH)


def on_application_stage_changed(_evt: ApplicationStageChanged) -> None:
    """Смена этапа воронки — тайминги/активная воронка (grid/search) и funnel (pulse)."""
    snapshot_dirty.mark_dirty(snapshot_dirty.GRID, snapshot_dirty.PULSE, snapshot_dirty.SEARCH)


def on_offer_received(_evt: OfferReceived) -> None:
    """Новый оффер — счётчики офферов (grid/search) и `weighted_offer_signal` (pulse)."""
    snapshot_dirty.mark_dirty(snapshot_dirty.GRID, snapshot_dirty.PULSE, snapshot_dirty.SEARCH)


def on_hr_message_received(_evt: HrMessageReceived) -> None:
    """HR-переписка разобрана — `hr_responses_30d` (grid/search) и `response_rate` (pulse)."""
    snapshot_dirty.mark_dirty(snapshot_dirty.GRID, snapshot_dirty.PULSE, snapshot_dirty.SEARCH)


def on_resume_updated(_evt: ResumeUpdated) -> None:
    """Резюме сохранено — `SearchProfile` (зарплата/форматы) поехал, гейты/бэнды затронуты
    в grid/pulse. Search-метрики от профиля не зависят — не метим."""
    snapshot_dirty.mark_dirty(snapshot_dirty.GRID, snapshot_dirty.PULSE)


async def on_search_track_changed(evt: SearchTrackChanged) -> None:
    """Второй трек вошёл/вышел из поиска — в промпте ситуации появляется другая занятость,
    кэш сводки больше не тот. Bootstrap (`account_id=0`) пропускаем.
    """
    snapshot_dirty.mark_dirty(snapshot_dirty.GRID, snapshot_dirty.PULSE)
    if not evt.account_id:
        return
    from core.domains.market.situation_store import clear_situation

    await clear_situation(account_id=evt.account_id)


SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (VacancyScored, on_vacancy_scored),
    (ApplicationStageChanged, on_application_stage_changed),
    (OfferReceived, on_offer_received),
    (HrMessageReceived, on_hr_message_received),
    (ResumeUpdated, on_resume_updated),
    (SearchTrackChanged, on_search_track_changed),
)
SUBSCRIBES: tuple[type, ...] = tuple(t for t, _ in SUBSCRIPTIONS)

__all__ = [
    "PUBLISHES",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "on_application_stage_changed",
    "on_hr_message_received",
    "on_offer_received",
    "on_resume_updated",
    "on_search_track_changed",
    "on_vacancy_scored",
]
