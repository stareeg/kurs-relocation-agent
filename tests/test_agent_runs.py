"""A-3 менеджер запусков: старт фоновой задачей, пауза, «да»/«нет», резюм после рестарта.

Стор — в памяти (`InMemoryRunsStore`), модели — скриптованные, чекпойнтер — MemorySaver
общий между «процессами» (тест «рестарта» создаёт второй менеджер с тем же чекпойнтером:
критерий A-3 — пауза, рестарт API, продолжение).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from core.app.agent.contracts import ToolContext
from core.app.agent.graph import AgentDeps
from core.app.agent.runs import AgentRunsManager, InvalidInput, NotFound
from core.app.agent.tools import TOOLS, ensure_tools_registered
from core.platform.repo.agent_runs import AgentEventRecord, AgentRunRecord
from tests.fakes import FakeDemoDb, ScriptedChatModel
from tests.test_agent_confirm import GOAL, NOTE, _plan_spec, _replan_spec

ensure_tools_registered()


class InMemoryRunsStore:
    """Двойник SQL-стора: та же поверхность, хранение — в списках этого теста."""

    def __init__(self) -> None:
        self.runs: dict[int, AgentRunRecord] = {}
        self.events: list[AgentEventRecord] = []
        self._next_run = 0
        self._next_event = 0

    async def create_run(
        self, *, account_id: int, goal: str, thread_id: str, session_id: int | None = None
    ) -> AgentRunRecord:
        self._next_run += 1
        record = AgentRunRecord(
            id=self._next_run,
            account_id=account_id,
            goal=goal,
            status="queued",
            thread_id=thread_id,
        )
        self.runs[record.id] = record
        return record

    async def get_run(self, run_id: int, *, account_id: int) -> AgentRunRecord | None:
        record = self.runs.get(run_id)
        if record is None or record.account_id != account_id:
            return None
        return record

    async def update_run(
        self,
        run_id: int,
        *,
        account_id: int,
        status: str | None = None,
        stop_reason: str | None = None,
        answer: str | None = None,
        error: str | None = None,
    ) -> AgentRunRecord | None:
        record = self.runs.get(run_id)
        if record is None or record.account_id != account_id:
            return None
        updates: dict[str, Any] = {}
        for name, value in (
            ("status", status),
            ("stop_reason", stop_reason),
            ("answer", answer),
            ("error", error),
        ):
            if value is not None:
                updates[name] = value
        self.runs[run_id] = record = replace(record, **updates)
        return record

    async def append_event(
        self,
        *,
        run_id: int,
        account_id: int,
        type: str,  # noqa: A002
        payload: dict[str, Any],
        node: str | None = None,
        duration_ms: float | None = None,
    ) -> int:
        self._next_event += 1
        self.events.append(
            AgentEventRecord(
                id=self._next_event, run_id=run_id, type=type, payload=payload, node=node
            )
        )
        return self._next_event

    async def list_events(
        self, *, run_id: int, account_id: int, after_id: int = 0, limit: int = 500
    ) -> list[AgentEventRecord]:
        return [e for e in self.events if e.run_id == run_id and e.id > after_id][:limit]

    def event_types(self, run_id: int) -> list[str]:
        return [e.type for e in self.events if e.run_id == run_id]


def _deps_factory(db: FakeDemoDb, *, action: str = "queue") -> Any:
    """Скриптованные модели: `queue` — карточка подтверждения, `search` — только поиск."""

    async def factory(account_id: int) -> AgentDeps:
        if action == "queue":
            executor = ScriptedChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "queue_application",
                                "args": {"vacancy_id": "demo-101", "cover_note": NOTE},
                                "id": "c1",
                            }
                        ],
                    ),
                    AIMessage(content="Действие отложено до подтверждения человека."),
                ]
            )
            plan = _plan_spec(("s1", "Поставить отклик", "отклик в очереди"))
        else:
            executor = ScriptedChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {"name": "search_vacancies", "args": {"query": "kestrel"}, "id": "c1"}
                        ],
                    ),
                    AIMessage(content="Нашёл вакансию Applied AI Engineer."),
                ]
            )
            plan = _plan_spec(("s1", "Найти вакансии", "список вакансий"))
        return AgentDeps(
            planner=ScriptedChatModel(responses=[AIMessage(content=json.dumps(plan))]),
            executor=executor,
            replanner=ScriptedChatModel(
                responses=[AIMessage(content=json.dumps(_replan_spec("finish")))]
            ),
            tools=TOOLS,
            tool_context=ToolContext(account_id=account_id, db=db),
        )

    return factory


async def _settle(
    manager: AgentRunsManager, run_id: int, *, terminal: bool = False
) -> AgentRunRecord | None:
    return await manager.wait_settled(run_id=run_id, account_id=1, terminal=terminal)


async def test_run_completes_without_action():
    """Цель без действий: задача живёт в фоне, стор получает done и события."""
    store = InMemoryRunsStore()
    manager = AgentRunsManager(
        store, deps_factory=_deps_factory(FakeDemoDb(), action="search"), checkpointer=MemorySaver()
    )
    record = await manager.start_run(account_id=1, goal="Найди вакансии backend")
    final = await _settle(manager, record.id, terminal=True)

    assert final.status == "done"
    assert final.stop_reason == "answered"
    types = store.event_types(record.id)
    assert types[0] == "run_started"
    assert "plan_created" in types
    assert "step_started" in types
    assert "observation" in types
    assert "node_timing" in types
    assert types[-1] == "done"


async def test_interrupt_then_approve_executes_action():
    """Пауза → «да»: статус waiting_approval, событие карточки, действие выполнено."""
    db = FakeDemoDb()
    store = InMemoryRunsStore()
    manager = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal=GOAL)

    waiting = await _settle(manager, record.id)
    assert waiting.status == "waiting_approval"
    card_events = [e for e in store.events if e.type == "needs_confirmation"]
    assert card_events and card_events[-1].run_id == record.id
    assert card_events[-1].payload["card"]["action"] == "queue_application"
    assert db.executed == []

    await manager.approve(run_id=record.id, account_id=1, approved=True)
    final = await _settle(manager, record.id, terminal=True)
    assert final.status == "done"
    writes = [sql for sql, _ in db.executed]
    assert any("auto_apply_queue_overrides" in sql for sql in writes)
    resolved = [e for e in store.events if e.type == "confirmation_resolved"]
    assert resolved and resolved[-1].payload["approved"] is True


async def test_pause_survives_restart_and_resumes():
    """Рестарт API: новый менеджер резюмит паузу с чекпойнта, «да» выполняет действие."""
    db = FakeDemoDb()
    saver = MemorySaver()
    store = InMemoryRunsStore()
    first = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=saver)
    record = await first.start_run(account_id=1, goal=GOAL)
    waiting = await _settle(first, record.id)
    assert waiting.status == "waiting_approval"

    # «Рестарт»: первый менеджер исчез вместе с процессом; стор и чекпойнтер остались.
    second = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=saver)
    await second.approve(run_id=record.id, account_id=1, approved=True)
    final = await _settle(second, record.id, terminal=True)
    assert final.status == "done"
    writes = [sql for sql, _ in db.executed]
    assert any("auto_apply_queue_overrides" in sql for sql in writes)


async def test_rejection_does_not_touch_db():
    db = FakeDemoDb()
    store = InMemoryRunsStore()
    manager = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal=GOAL)
    waiting = await _settle(manager, record.id)
    assert waiting.status == "waiting_approval"

    await manager.approve(run_id=record.id, account_id=1, approved=False)
    final = await _settle(manager, record.id, terminal=True)
    assert final.status == "done"
    assert db.executed == []


async def test_approval_of_finished_run_is_rejected():
    """Подтверждение для запуска, который не ждёт — InvalidInput; чужой запуск — NotFound."""
    store = InMemoryRunsStore()
    manager = AgentRunsManager(
        store, deps_factory=_deps_factory(FakeDemoDb(), action="search"), checkpointer=MemorySaver()
    )
    record = await manager.start_run(account_id=1, goal="Найди вакансии backend")
    await _settle(manager, record.id)

    with pytest.raises(InvalidInput):
        await manager.approve(run_id=record.id, account_id=1, approved=True)
    with pytest.raises(NotFound):
        await manager.approve(run_id=999, account_id=1, approved=True)


async def test_approve_with_edit_records_edited_fields():
    """«Да» с правкой текста: событие знает, что правили, в базу ушёл текст человека."""
    db = FakeDemoDb()
    store = InMemoryRunsStore()
    manager = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal=GOAL)
    await _settle(manager, record.id)
    edited = "Здравствуйте! Текст поправлен человеком перед отправкой, без выдуманных фактов."
    await manager.approve(
        run_id=record.id, account_id=1, approved=True, edits={"cover_note": edited}
    )
    final = await _settle(manager, record.id, terminal=True)
    assert final.status == "done"
    resolved = [e for e in store.events if e.type == "confirmation_resolved"]
    assert resolved[-1].payload == {"approved": True, "edited": ["cover_note"]}
    assert any(edited in str(args) for _, args in db.executed)


async def test_auto_confirm_run_never_waits():
    """Запуск в режиме «подтверждать автоматически»: без waiting_approval, отклик в очереди."""
    db = FakeDemoDb()
    store = InMemoryRunsStore()
    manager = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal=GOAL, auto_confirm=True)
    final = await _settle(manager, record.id, terminal=True)
    assert final.status == "done"
    types = store.event_types(record.id)
    assert "needs_confirmation" not in types
    started = [e for e in store.events if e.type == "run_started"]
    assert started[-1].payload["auto_confirm"] is True
    auto = [e for e in store.events if e.type == "confirmation_resolved"]
    assert auto and auto[-1].payload["auto"] is True
    assert any("auto_apply_queue_overrides" in sql for sql, _ in db.executed)


# ---------------------------------------------------------------- A-9: «Стоп»


class _HangingChatModel(ScriptedChatModel):
    """Модель, которая «думает» дольше теста: отмена приходит посреди вызова."""

    async def _agenerate(self, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(30)
        raise AssertionError("отменённый запуск не должен дождаться модели")


async def _until_status(store: InMemoryRunsStore, run_id: int, status: str) -> None:
    for _ in range(300):
        record = await store.get_run(run_id, account_id=1)
        if record is not None and record.status == status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"запуск не дошёл до {status}")


async def test_cancel_running_run_mid_model_call():
    """«Стоп» посреди вызова модели: cancelled, честный итог, терминальное событие."""
    db = FakeDemoDb()
    store = InMemoryRunsStore()
    base = _deps_factory(db, action="search")

    async def factory(account_id: int) -> AgentDeps:
        deps = await base(account_id)
        return replace(deps, planner=_HangingChatModel(responses=[AIMessage(content="{}")]))

    manager = AgentRunsManager(store, deps_factory=factory, checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal="Найди вакансии backend")
    await _until_status(store, record.id, "running")

    await manager.cancel(run_id=record.id, account_id=1)
    final = await _settle(manager, record.id, terminal=True)
    assert final.status == "cancelled"
    assert final.stop_reason == "cancelled"
    assert "остановлен человеком" in (final.answer or "")
    types = store.event_types(record.id)
    assert types[-1] == "cancelled"
    assert db.executed == []


async def test_cancel_waiting_run_does_not_execute_action():
    """«Стоп» на паузе: действие не выполнено и названо в итоге невыполненным."""
    db = FakeDemoDb()
    store = InMemoryRunsStore()
    manager = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal=GOAL)
    assert (await _settle(manager, record.id)).status == "waiting_approval"

    await manager.cancel(run_id=record.id, account_id=1)
    final = await _settle(manager, record.id, terminal=True)
    assert final.status == "cancelled"
    assert "Действие не выполнено: queue_application" in (final.answer or "")
    assert db.executed == [], "отмена не выполняет действие"
    cancelled = [e for e in store.events if e.type == "cancelled"]
    assert cancelled and cancelled[-1].payload["stop_reason"] == "cancelled"
    with pytest.raises(InvalidInput):
        await manager.approve(run_id=record.id, account_id=1, approved=True)


async def test_cancel_pause_after_restart_uses_checkpoint():
    """Пауза пережила рестарт (живой задачи нет): итог отмены — по чекпойнту."""
    db = FakeDemoDb()
    saver = MemorySaver()
    store = InMemoryRunsStore()
    first = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=saver)
    record = await first.start_run(account_id=1, goal=GOAL)
    assert (await _settle(first, record.id)).status == "waiting_approval"

    second = AgentRunsManager(store, deps_factory=_deps_factory(db), checkpointer=saver)
    await second.cancel(run_id=record.id, account_id=1)
    final = await store.get_run(record.id, account_id=1)
    assert final is not None and final.status == "cancelled"
    assert "Действие не выполнено: queue_application" in (final.answer or "")
    assert store.event_types(record.id)[-1] == "cancelled"
    assert db.executed == []


async def test_cancel_finished_or_unknown_run_is_rejected():
    store = InMemoryRunsStore()
    manager = AgentRunsManager(
        store, deps_factory=_deps_factory(FakeDemoDb(), action="search"), checkpointer=MemorySaver()
    )
    record = await manager.start_run(account_id=1, goal="Найди вакансии backend")
    await _settle(manager, record.id, terminal=True)
    with pytest.raises(InvalidInput):
        await manager.cancel(run_id=record.id, account_id=1)
    with pytest.raises(NotFound):
        await manager.cancel(run_id=999, account_id=1)
