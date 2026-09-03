"""A-22: карьерная лента — DomainEvent → career_timeline."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.app.subscriptions import register_domain_subscriptions
from core.domains.career import events as career_events
from core.domains.career.timeline import (
    timeline_from_interview_debriefed,
    timeline_from_offer_received,
    timeline_from_stage_changed,
)
from core.kernel import ports
from core.kernel.events import (
    ApplicationStageChanged,
    InterviewDebriefed,
    OfferReceived,
    VacancyDeduplicated,
)
from core.kernel.ids import OfferId, VacancyId
from core.kernel.schemas.funnel import FunnelStatus


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def test_stage_changed_to_applied_is_application_kind() -> None:
    evt = ApplicationStageChanged(
        vacancy_id=VacancyId("hh-1"),
        job_id=10,
        stage=FunnelStatus.APPLIED.value,
        previous_stage=FunnelStatus.VIEWED.value,
        source="api_kanban",
    )
    row = timeline_from_stage_changed(evt)
    assert row is not None
    assert row.kind == "application"
    assert row.title.startswith("Отклик")
    assert row.source_ref == "hh-1"
    assert row.payload["stage"] == FunnelStatus.APPLIED.value
    assert row.payload["previous_stage"] == FunnelStatus.VIEWED.value


def test_stage_changed_tech_is_stage_kind() -> None:
    evt = ApplicationStageChanged(
        vacancy_id=VacancyId("v1"),
        stage=FunnelStatus.TECH.value,
        previous_stage=FunnelStatus.SCREENING.value,
    )
    row = timeline_from_stage_changed(evt)
    assert row is not None
    assert row.kind == "stage"
    assert row.title == f"{FunnelStatus.SCREENING.value} → {FunnelStatus.TECH.value} · v1"


def test_stage_offer_is_offer_kind() -> None:
    row = timeline_from_stage_changed(
        ApplicationStageChanged(
            vacancy_id=VacancyId("v2"),
            stage=FunnelStatus.OFFER.value,
            previous_stage=FunnelStatus.FINAL.value,
        )
    )
    assert row is not None
    assert row.kind == "offer"
    assert "Оффер" in row.title


def test_viewed_and_noop_are_skipped() -> None:
    assert (
        timeline_from_stage_changed(
            ApplicationStageChanged(stage=FunnelStatus.VIEWED.value, vacancy_id=VacancyId("v"))
        )
        is None
    )
    assert (
        timeline_from_stage_changed(
            ApplicationStageChanged(
                stage=FunnelStatus.TECH.value,
                previous_stage=FunnelStatus.TECH.value,
                vacancy_id=VacancyId("v"),
            )
        )
        is None
    )


def test_offer_and_debrief_mappers() -> None:
    offer = timeline_from_offer_received(
        OfferReceived(
            offer_id=OfferId("gm_1"),
            vacancy_id=VacancyId("gm_1"),
            company="Acme",
            status="received",
        )
    )
    assert offer is not None
    assert offer.kind == "offer"
    assert offer.title == "Оффер · Acme"

    debrief = timeline_from_interview_debriefed(
        InterviewDebriefed(
            vacancy_id=VacancyId("v3"),
            stage="Техничка",
            signal="strong",
            debrief_id=9,
        )
    )
    assert debrief is not None
    assert debrief.kind == "other"
    assert "Разбор" in debrief.title
    assert debrief.payload["debrief_id"] == 9


def test_debrief_signal_is_translated_to_russian_label() -> None:
    """0152/Этап 1.5: enum-значение сигнала не должно течь в UI как есть."""
    debrief = timeline_from_interview_debriefed(
        InterviewDebriefed(vacancy_id=VacancyId("v9"), stage="final", signal="offer_likely")
    )
    assert debrief is not None
    assert "offer_likely" not in debrief.title
    assert "Похоже на оффер" in debrief.title
    # Сырое значение остаётся в payload — фильтры/аналитика по нему не ломаются.
    assert debrief.payload["signal"] == "offer_likely"


def test_vacancy_deduplicated_no_longer_subscribed() -> None:
    """Решение владельца 2026-08-26 (plans/career_redesign_2026_08_26.md): «Дубль вакансии»
    убран из ленты карьеры совсем — career больше не реагирует на VacancyDeduplicated."""
    assert VacancyDeduplicated not in career_events.SUBSCRIBES
    assert not hasattr(career_events, "on_vacancy_deduplicated")

    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    career_handlers = [
        h
        for h in bus.handlers_for(VacancyDeduplicated())
        if getattr(h, "__module__", "").endswith("career.events")
    ]
    assert career_handlers == []


async def test_stage_change_subscription_writes_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Критерий A-22: после смены этапа в воронке в ленте появляется запись."""
    inserted: list[object] = []

    async def _insert(event, *, account_id=None, db=None):
        inserted.append(event)
        return event

    monkeypatch.setattr(
        "core.domains.career.timeline.insert_timeline_event",
        _insert,
    )

    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    await bus.publish_and_wait(
        ApplicationStageChanged(
            vacancy_id=VacancyId("vac-42"),
            job_id=42,
            stage=FunnelStatus.SCREENING.value,
            previous_stage=FunnelStatus.APPLIED.value,
            source="api_funnel",
            account_id=1,
        )
    )

    assert len(inserted) == 1
    row = inserted[0]
    assert row.kind == "stage"
    assert row.source_ref == "vac-42"
    assert row.payload["job_id"] == 42


async def test_viewed_subscription_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert = AsyncMock()
    monkeypatch.setattr("core.domains.career.timeline.insert_timeline_event", insert)

    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    await bus.publish_and_wait(
        ApplicationStageChanged(
            vacancy_id=VacancyId("v"),
            stage=FunnelStatus.VIEWED.value,
        )
    )
    insert.assert_not_awaited()


def test_career_stage_handler_registered() -> None:
    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    names = {h.__name__ for h in bus.handlers_for(ApplicationStageChanged())}
    assert "on_application_stage_changed" in names
    # preparation (HR-скрининг) и career (лента) — оба на одном событии.
    assert len([n for n in names if n == "on_application_stage_changed"]) >= 1
    career_handlers = [
        h
        for h in bus.handlers_for(ApplicationStageChanged())
        if getattr(h, "__module__", "").endswith("career.events")
    ]
    assert len(career_handlers) == 1
