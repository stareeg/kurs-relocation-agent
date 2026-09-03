"""События домена career: подписки на шину → лента и факты.

Career сам почти ничего не публикует (пока). Слушает чужие события первой очереди:
пишет `career_timeline`, а из разбора собеса — `career_facts` (долгая память).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.kernel.events import (
    ApplicationStageChanged,
    InterviewDebriefed,
    OfferReceived,
    SearchModeChanged,
    SearchTrackChanged,
)

PUBLISHES: tuple[type, ...] = (SearchModeChanged, SearchTrackChanged)


async def on_application_stage_changed(evt: ApplicationStageChanged) -> None:
    """Смена этапа воронки → строка в `career_timeline` (критерий A-22)."""
    from core.domains.career.timeline import record_domain_event

    await record_domain_event(evt)


async def on_offer_received(evt: OfferReceived) -> None:
    from core.domains.career.portfolio import record_portfolio_from_offer
    from core.domains.career.timeline import record_domain_event

    await record_domain_event(evt)
    # Этап 5.2 (plans/career_redesign_2026_08_26.md): оффер → достижение в портфолио.
    await record_portfolio_from_offer(evt, account_id=evt.account_id)


async def on_interview_debriefed(evt: InterviewDebriefed) -> None:
    from core.domains.career.facts import record_facts_from_debrief
    from core.domains.career.portfolio import record_portfolio_from_debrief
    from core.domains.career.timeline import record_domain_event

    await record_domain_event(evt)
    # A-28: факты из разбора → career_facts (читаются в prep/chat).
    await record_facts_from_debrief(evt, account_id=evt.account_id)
    # Этап 5.2: разбор с сильными ответами → достижение в портфолио.
    await record_portfolio_from_debrief(evt, account_id=evt.account_id)


async def on_search_mode_changed(evt: SearchModeChanged) -> None:
    """Переход режима поиска → строка в `career_timeline`."""
    from core.domains.career.timeline import record_domain_event

    await record_domain_event(evt)


async def on_search_track_changed(evt: SearchTrackChanged) -> None:
    """Переход набора треков поиска → строка в `career_timeline`."""
    from core.domains.career.timeline import record_domain_event

    await record_domain_event(evt)


SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (ApplicationStageChanged, on_application_stage_changed),
    (OfferReceived, on_offer_received),
    (InterviewDebriefed, on_interview_debriefed),
    (SearchModeChanged, on_search_mode_changed),
    (SearchTrackChanged, on_search_track_changed),
)
SUBSCRIBES: tuple[type, ...] = tuple(t for t, _ in SUBSCRIPTIONS)

__all__ = [
    "PUBLISHES",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "on_application_stage_changed",
    "on_interview_debriefed",
    "on_offer_received",
    "on_search_mode_changed",
    "on_search_track_changed",
]
