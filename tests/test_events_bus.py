"""A-11: шина доменных событий — доставка, изоляция подписчика, журнал, подписки доменов.

Три вещи, ради которых шина вводилась:
1. издатель не знает подписчиков (прямой вызов чужого домена из `add_stage` заменён событием);
2. падение подписчика не ломает издателя и не отменяет остальных подписчиков;
3. каждое событие видно в витрине `copilot_logs` (журнал — обычная строка лога, отдельной
   таблицы намеренно нет).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.app.subscriptions import DOMAINS, register_domain_subscriptions
from core.kernel import ports
from core.kernel.events import (
    FIRST_ORDER_EVENTS,
    ApplicationStageChanged,
    DomainEvent,
    ResumeUpdated,
    VacancyScored,
)
from core.kernel.schemas.funnel import FunnelStatus
from core.platform.events.journal import CATEGORY, log_domain_event
from core.platform.observability.logging import record_to_dict


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


# --------------------------------------------------------------------------- модели событий


def test_events_carry_ids_not_payloads():
    """Событие несёт идентификаторы, а не доменные модели: иначе шина — скрытый транспорт."""
    evt = VacancyScored(
        vacancy_id="v1", job_id=7, overall_score=81.5, recommendation="apply", account_id=1
    )
    assert evt.name == "VacancyScored"
    assert evt.subject == "v1"
    assert evt.to_fields() == {
        "vacancy_id": "v1",
        "job_id": 7,
        "overall_score": 81.5,
        "recommendation": "apply",
        "account_id": 1,
    }
    assert evt.occurred_at.tzinfo is not None  # aware: иначе время в витрине разъедется с БД


def test_event_fields_skip_empty_and_keep_payload():
    evt = ResumeUpdated(source="resume_put", payload={"fields": 3}, account_id=1)
    assert evt.to_fields() == {
        "source": "resume_put",
        "account_id": 1,
        "payload": {"fields": 3},
    }
    assert ResumeUpdated().to_fields() == {"account_id": 0}


def test_first_order_events_are_domain_events():
    for event_type in FIRST_ORDER_EVENTS:
        assert issubclass(event_type, DomainEvent), event_type


# --------------------------------------------------------------------------- доставка


def test_publish_reaches_subscriber():
    seen: list[VacancyScored] = []
    bus = ports.InProcessEventBus()
    bus.subscribe(VacancyScored, seen.append)

    bus.publish(VacancyScored(vacancy_id="v1"))

    assert [e.vacancy_id for e in seen] == ["v1"]


def test_subscriber_of_base_type_gets_everything():
    """Подписка на `DomainEvent` — то, как к шине подключается журнал и будущая аналитика."""
    seen: list[str] = []
    bus = ports.InProcessEventBus()
    bus.subscribe(DomainEvent, lambda e: seen.append(e.name))

    bus.publish(VacancyScored(vacancy_id="v1"))
    bus.publish(ResumeUpdated())

    assert seen == ["VacancyScored", "ResumeUpdated"]


def test_other_event_types_are_not_delivered():
    seen: list[Any] = []
    bus = ports.InProcessEventBus()
    bus.subscribe(VacancyScored, seen.append)

    bus.publish(ResumeUpdated())

    assert seen == []


def test_failing_subscriber_does_not_break_publisher_or_neighbours(caplog):
    seen: list[str] = []
    bus = ports.InProcessEventBus()

    def boom(_evt: Any) -> None:
        raise RuntimeError("подписчик упал")

    bus.subscribe(VacancyScored, boom)
    bus.subscribe(VacancyScored, lambda _e: seen.append("ok"))

    with caplog.at_level(logging.WARNING):
        bus.publish(VacancyScored(vacancy_id="v1"))  # издатель не должен ничего заметить

    assert seen == ["ok"]
    assert "boom" in caplog.text


async def test_publish_and_wait_awaits_async_subscriber():
    order: list[str] = []
    bus = ports.InProcessEventBus()

    async def slow(_evt: Any) -> None:
        await asyncio.sleep(0.01)
        order.append("subscriber")

    bus.subscribe(VacancyScored, slow)
    await bus.publish_and_wait(VacancyScored(vacancy_id="v1"))
    order.append("publisher")

    assert order == ["subscriber", "publisher"]  # эффект завершён до возврата издателю


async def test_publish_and_wait_isolates_failing_async_subscriber():
    seen: list[str] = []
    bus = ports.InProcessEventBus()

    async def boom(_evt: Any) -> None:
        raise RuntimeError("подписчик упал")

    async def ok(_evt: Any) -> None:
        seen.append("ok")

    bus.subscribe(VacancyScored, boom)
    bus.subscribe(VacancyScored, ok)

    await bus.publish_and_wait(VacancyScored(vacancy_id="v1"))
    assert seen == ["ok"]


async def test_publish_schedules_async_subscriber_in_background():
    seen: list[str] = []
    bus = ports.InProcessEventBus()

    async def handler(_evt: Any) -> None:
        seen.append("done")

    bus.subscribe(VacancyScored, handler)
    bus.publish(VacancyScored(vacancy_id="v1"))

    assert seen == []  # publish не ждёт
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert seen == ["done"]


def test_publish_outside_event_loop_warns_instead_of_crashing(caplog):
    """CLI-скрипт без loop не должен падать из-за асинхронного подписчика."""
    bus = ports.InProcessEventBus()

    async def handler(_evt: Any) -> None:  # pragma: no cover — не будет вызван
        pass

    bus.subscribe(VacancyScored, handler)
    with caplog.at_level(logging.WARNING):
        bus.publish(VacancyScored(vacancy_id="v1"))

    assert "publish_and_wait" in caplog.text


def test_subscribe_is_idempotent():
    """`wire_default_ports()` зовут и api, и бот в одном процессе — эффект не должен задваиваться."""
    seen: list[str] = []
    bus = ports.InProcessEventBus()

    def handler(_evt: Any) -> None:
        seen.append("hit")

    bus.subscribe(VacancyScored, handler)
    bus.subscribe(VacancyScored, handler)

    bus.publish(VacancyScored(vacancy_id="v1"))
    assert seen == ["hit"]


# --------------------------------------------------------------------------- журнал


def test_journal_is_called_and_its_failure_does_not_stop_delivery():
    seen: list[str] = []

    def broken_journal(_evt: Any) -> None:
        raise RuntimeError("витрина недоступна")

    bus = ports.InProcessEventBus(journal=broken_journal)
    bus.subscribe(VacancyScored, lambda _e: seen.append("ok"))

    bus.publish(VacancyScored(vacancy_id="v1"))
    assert seen == ["ok"]


def test_journal_row_shape_for_copilot_logs(caplog):
    """Строка журнала = то, что PgLogSink положит в `copilot_logs` (категория + поля события)."""
    with caplog.at_level(logging.INFO, logger="core.events"):
        log_domain_event(VacancyScored(vacancy_id="v1", job_id=7, recommendation="apply"))

    records = [r for r in caplog.records if r.name == "core.events"]
    assert len(records) == 1
    row = record_to_dict(records[0])
    assert row["level"] == "INFO"
    assert row["event"] == CATEGORY
    assert "VacancyScored" in row["msg"] and "v1" in row["msg"]
    fields = row["fields"]
    assert fields["event_name"] == "VacancyScored"
    assert fields["subject"] == "v1"
    assert fields["job_id"] == 7
    assert fields["recommendation"] == "apply"


def test_journal_survives_event_without_contract():
    """Журнал берёт событие структурно — чужой объект не должен ронять публикацию."""

    class Bare:
        pass

    log_domain_event(Bare())  # не падает и не требует to_fields/subject


# --------------------------------------------------------------------------- подписки доменов


def test_every_domain_declares_the_event_form():
    import importlib

    for domain in DOMAINS:
        module = importlib.import_module(f"core.domains.{domain}.events")
        assert isinstance(module.PUBLISHES, tuple)
        assert isinstance(module.SUBSCRIPTIONS, tuple)
        for event_type in module.PUBLISHES:
            assert issubclass(event_type, DomainEvent), (domain, event_type)
        for event_type, handler in module.SUBSCRIPTIONS:
            assert issubclass(event_type, DomainEvent), (domain, event_type)
            assert callable(handler), (domain, handler)


def test_every_first_order_event_has_a_publisher():
    """Событие без издателя — мёртвая декларация; A-11 обещает семь живых."""
    import importlib

    published: set[type] = set()
    for domain in DOMAINS:
        published.update(importlib.import_module(f"core.domains.{domain}.events").PUBLISHES)
    assert set(FIRST_ORDER_EVENTS) == published


def test_register_domain_subscriptions_binds_handlers():
    bus = ports.InProcessEventBus()
    total = register_domain_subscriptions(bus)
    assert total >= 1

    handlers = bus.handlers_for(ApplicationStageChanged(stage=FunnelStatus.TECH.value))
    assert any(h.__name__ == "on_application_stage_changed" for h in handlers)

    # Повторная регистрация (api + бот в одном процессе) не задваивает подписчиков.
    before = len(handlers)
    register_domain_subscriptions(bus)
    assert len(bus.handlers_for(ApplicationStageChanged())) == before


def test_wire_default_ports_binds_bus_with_journal():
    from core.app.wiring import wire_default_ports
    from core.platform.events import log_domain_event as journal

    wire_default_ports(force=True)
    bus = ports.events()
    assert isinstance(bus, ports.InProcessEventBus)
    assert bus._journal is journal  # noqa: SLF001 — проверяем именно связку корня
    assert bus.handlers_for(ApplicationStageChanged())


# ------------------------------------------------- сценарий: смена стадии вместо прямого вызова


async def test_tech_stage_marks_hr_screening_via_subscription(monkeypatch: pytest.MonkeyPatch):
    """Переход в «Техничку» гасит кружок HR-скрининга — теперь через подписку preparation."""
    ensure = AsyncMock()
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_completed", ensure
    )

    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    await bus.publish_and_wait(
        ApplicationStageChanged(vacancy_id="v1", stage=FunnelStatus.TECH.value, account_id=7)
    )
    ensure.assert_awaited_once_with("v1", account_id=7)

    ensure.reset_mock()
    await bus.publish_and_wait(
        ApplicationStageChanged(vacancy_id="v1", stage=FunnelStatus.APPLIED.value, account_id=7)
    )
    ensure.assert_not_awaited()  # другие стадии подписчика не касаются


class _FakeDb:
    """Минимальный Executor: add_stage делает select текущей строки, insert stage и update."""

    def __init__(self, status: str = "Отклик", vacancy_id: str = "v1") -> None:
        self.status = status
        self.vacancy_id = vacancy_id
        self.executed: list[str] = []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any]:
        if sql.startswith("select vacancy_id, status"):
            return {"vacancy_id": self.vacancy_id, "status": self.status}
        return {"id": 1, "job_id": args[0], "stage": args[1], "source": args[2], "changed_at": None}

    async def execute(self, sql: str, *args: Any) -> None:
        self.executed.append(sql)


async def test_add_stage_publishes_event_with_previous_stage():
    from core.domains.opportunities.jobs import add_stage

    seen: list[ApplicationStageChanged] = []
    bus = ports.InProcessEventBus()
    bus.subscribe(ApplicationStageChanged, seen.append)

    with ports.use_ports(events=bus):
        stage = await add_stage(
            42, FunnelStatus.TECH.value, source="api_kanban", account_id=1, db=_FakeDb()
        )

    assert stage.stage == FunnelStatus.TECH.value
    assert len(seen) == 1
    evt = seen[0]
    assert (evt.vacancy_id, evt.job_id, evt.stage, evt.previous_stage, evt.source) == (
        "v1",
        42,
        FunnelStatus.TECH.value,
        "Отклик",
        "api_kanban",
    )

