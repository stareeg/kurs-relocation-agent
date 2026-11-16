"""Менеджер фоновых запусков агента (A-3): старт, пауза на «да», резюм, события.

Запуск — задача asyncio в процессе API, но её след в Postgres (`agent_runs`):
статус и события переживают рестарт. Пауза — это interrupt графа на узле `confirm`:
состояние лежит в чекпойнте Postgres, менеджер ждёт решения в очереди; «да» →
`Command(resume=…)` с того же чекпойнта — критерий A-3 «пауза, рестарт, продолжение»
(новый процесс строит граф заново и резюмит с сохранённого состояния).

События: узловые таймеры и содержательные события пишутся в `agent_events` (pump,
единый порядок) и раздаются живым SSE-подписчикам; без живой задачи SSE читает догон
из базы. Брошенные `running`/`queued` после рестарта честно закрываются как failed
(`recover_after_restart`), пауза (`waiting_approval`) остаётся ждать «да».
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from core.app.agent.budget import RunBudget, budget_from, put_budget, run_limits_payload
from core.app.agent.events import AgentEvent
from core.app.agent.graph import AgentDeps, build_agent_graph, cancelled_answer, default_deps
from core.app.agent.state import RunLimits
from core.kernel.errors import InvalidInput, NotFound
from core.platform.config.runtime import reset_current_agent_run_id, set_current_agent_run_id
from core.platform.repo import agent_runs as runs_repo
from core.platform.repo.agent_runs import AgentEventRecord, AgentRunRecord

logger = logging.getLogger(__name__)

TERMINAL_EVENT_TYPES = frozenset({"done", "failed", "cancelled"})
"""События, закрывающие SSE-поток запуска."""


class RunsStore(Protocol):
    """Поверхность хранилища запусков (прод — SQL, тесты — память)."""

    async def create_run(
        self, *, account_id: int, goal: str, thread_id: str, session_id: int | None = None
    ) -> AgentRunRecord: ...

    async def get_run(self, run_id: int, *, account_id: int) -> AgentRunRecord | None: ...

    async def update_run(
        self,
        run_id: int,
        *,
        account_id: int,
        status: str | None = None,
        stop_reason: str | None = None,
        answer: str | None = None,
        error: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> AgentRunRecord | None: ...

    async def append_event(
        self,
        *,
        run_id: int,
        account_id: int,
        type: str,  # noqa: A002 — имя колонки
        payload: dict[str, Any],
        node: str | None = None,
        duration_ms: float | None = None,
    ) -> int: ...

    async def list_events(
        self, *, run_id: int, account_id: int, after_id: int = 0, limit: int = 500
    ) -> list[AgentEventRecord]: ...


class PgRunsStore:
    """SQL-стор запусков: тонкий адаптер модульных функций `platform/repo/agent_runs`."""

    async def create_run(
        self, *, account_id: int, goal: str, thread_id: str, session_id: int | None = None
    ) -> AgentRunRecord:
        return await runs_repo.create_run(
            account_id=account_id, goal=goal, thread_id=thread_id, session_id=session_id
        )

    async def get_run(self, run_id: int, *, account_id: int) -> AgentRunRecord | None:
        return await runs_repo.get_run(run_id, account_id=account_id)

    async def update_run(
        self,
        run_id: int,
        *,
        account_id: int,
        status: str | None = None,
        stop_reason: str | None = None,
        answer: str | None = None,
        error: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> AgentRunRecord | None:
        return await runs_repo.update_run(
            run_id,
            account_id=account_id,
            status=status,
            stop_reason=stop_reason,
            answer=answer,
            error=error,
            usage=usage,
        )

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
        return await runs_repo.append_event(
            run_id=run_id,
            account_id=account_id,
            type=type,
            payload=payload,
            node=node,
            duration_ms=duration_ms,
        )

    async def list_events(
        self, *, run_id: int, account_id: int, after_id: int = 0, limit: int = 500
    ) -> list[AgentEventRecord]:
        return await runs_repo.list_events(
            run_id=run_id, account_id=account_id, after_id=after_id, limit=limit
        )


DepsFactory = Callable[[int], Awaitable[AgentDeps]]


async def _default_deps_factory(account_id: int) -> AgentDeps:
    return default_deps(account_id)


@dataclass(slots=True)
class _LiveRun:
    """Живой запуск в этом процессе: задача, очередь решений и подписчики SSE."""

    run_id: int
    account_id: int
    thread_id: str
    goal: str
    session_id: int | None
    status: str = "queued"
    decisions: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    subscribers: list[asyncio.Queue[AgentEventRecord]] = field(default_factory=list)
    pump: _EventPump | None = None
    task: asyncio.Task[None] | None = None
    # «Стоп» человека (A-9): отличает отмену запуска от остановки процесса, где
    # CancelledError должен уйти наверх, а пауза — пережить рестарт.
    cancel_requested: bool = False


class _EventPump:
    """События узлов → хранилище (монотонный id) → живым подписчикам, в порядке прихода."""

    def __init__(self, store: RunsStore, live: _LiveRun) -> None:
        self._store = store
        self._live = live
        self._queue: asyncio.Queue[AgentEvent | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def emit(self, event: AgentEvent) -> None:
        """Синхронный наблюдатель: события узлов приходят из того же event loop."""
        self._queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[AgentEventRecord]:
        """Очередь живого подписчика (SSE). Дедупликация по id — на стороне подписчика."""
        queue: asyncio.Queue[AgentEventRecord] = asyncio.Queue()
        self._live.subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AgentEventRecord]) -> None:
        if queue in self._live.subscribers:
            self._live.subscribers.remove(queue)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"agent-events-{self._live.run_id}")

    async def close(self) -> None:
        self._queue.put_nowait(None)
        if self._task is not None:
            try:
                await self._task
            except Exception:  # noqa: BLE001 — pump не должен ронять запуск
                logger.exception("agent-events pump: сбой записи событий run=%s", self._live.run_id)

    async def _run(self) -> None:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            seq = await self._store.append_event(
                run_id=self._live.run_id,
                account_id=self._live.account_id,
                type=event.type,
                payload=event.payload,
                node=event.node,
                duration_ms=event.duration_ms,
            )
            record = AgentEventRecord(
                id=seq,
                run_id=self._live.run_id,
                type=event.type,
                payload=event.payload,
                node=event.node,
                duration_ms=event.duration_ms,
            )
            for queue in list(self._live.subscribers):
                queue.put_nowait(record)


class AgentRunsManager:
    """Реестр запусков: строки в Postgres, задачи — здесь, паузы — на чекпойнте графа."""

    def __init__(
        self,
        store: RunsStore | None = None,
        *,
        deps_factory: DepsFactory | None = None,
        checkpointer: Any | None = None,
    ) -> None:
        self._store: RunsStore = store or PgRunsStore()
        self._deps_factory = deps_factory or _default_deps_factory
        self._checkpointer = checkpointer
        self._live: dict[int, _LiveRun] = {}

    @property
    def ready(self) -> bool:
        """Запуски возможны: есть чекпойнтер (Postgres). Без него пауза не продолжится."""
        return self._checkpointer is not None

    def set_checkpointer(self, saver: Any) -> None:
        self._checkpointer = saver

    def set_deps_factory(self, factory: DepsFactory) -> None:
        self._deps_factory = factory

    async def start_run(
        self,
        *,
        account_id: int,
        goal: str,
        session_id: int | None = None,
        auto_confirm: bool = False,
    ) -> AgentRunRecord:
        """Создать строку и поднять задачу запуска. Живёт после отключения клиента.

        `auto_confirm` — режим «подтверждать автоматически» (OQ-8): кладётся в состояние
        на старте и действует на весь запуск, переключатель влияет на следующие запуски.
        """
        record = await self._store.create_run(
            account_id=account_id,
            goal=goal,
            thread_id=f"agent-run-{uuid.uuid4().hex[:16]}",
            session_id=session_id,
        )
        live = _LiveRun(
            run_id=record.id,
            account_id=account_id,
            thread_id=record.thread_id,
            goal=goal,
            session_id=session_id,
        )
        self._live[record.id] = live
        live.task = asyncio.create_task(
            self._run_loop(live, initial={"goal": goal, "auto_confirm": auto_confirm}),
            name=f"agent-run-{record.id}",
        )
        return record

    async def approve(
        self,
        *,
        run_id: int,
        account_id: int,
        approved: bool,
        edits: dict[str, Any] | None = None,
    ) -> AgentRunRecord:
        """Решение человека по паузе. Живая задача — очередь; после рестарта — резюм с чекпойнта.

        `edits` — правка карточки перед «да» (текст письма); какие поля можно править,
        решает узел `confirm` (`EDITABLE_PARAMS`), остальное он молча отбросит.
        """
        record = await self._store.get_run(run_id, account_id=account_id)
        if record is None:
            raise NotFound(f"запуск {run_id} не найден")
        if record.status != "waiting_approval":
            raise InvalidInput(f"запуск {run_id} не ждёт подтверждения (статус {record.status})")
        decision: dict[str, Any] = {"approved": approved}
        if approved and edits:
            decision["edits"] = dict(edits)
        live = self._live.get(run_id)
        if live is not None:
            live.decisions.put_nowait(decision)
        else:
            # Пауза пережила перезапуск API: строим граф заново, резюмим с чекпойнта.
            live = _LiveRun(
                run_id=record.id,
                account_id=account_id,
                thread_id=record.thread_id,
                goal=record.goal,
                session_id=record.session_id,
                status="waiting_approval",
            )
            self._live[run_id] = live
            live.task = asyncio.create_task(
                self._run_loop(live, resume=decision), name=f"agent-run-{run_id}"
            )
        return record

    def subscribe_live(self, run_id: int) -> asyncio.Queue[AgentEventRecord] | None:
        """Очередь живого запуска или None (SSE пойдёт поллом базы)."""
        live = self._live.get(run_id)
        if live is None or live.pump is None:
            return None
        return live.pump.subscribe()

    def unsubscribe_live(self, run_id: int, queue: asyncio.Queue[AgentEventRecord]) -> None:
        live = self._live.get(run_id)
        if live is not None and live.pump is not None:
            live.pump.unsubscribe(queue)

    async def stop_all(self) -> None:
        """Остановить задачи на shutdown; статусы закроет `recover_after_restart` на старте."""
        for live in list(self._live.values()):
            if live.task is not None and not live.task.done():
                live.task.cancel()
                with suppress(asyncio.CancelledError):
                    await live.task

    async def wait_settled(
        self, *, run_id: int, account_id: int, timeout: float = 3.0, terminal: bool = False
    ) -> AgentRunRecord | None:
        """Дождаться, пока запуск дойдёт до терминала или паузы на подтверждении.

        Тестам — основной хук: по умолчанию ждёт статуса, где задача не работает
        (done/failed/waiting_approval); с `terminal=True` — только done/failed
        (после approve: статус ещё пауза, а решение уже в очереди).
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        stops = (
            ("done", "failed", "cancelled")
            if terminal
            else (
                "done",
                "failed",
                "waiting_approval",
                "cancelled",
            )
        )
        while loop.time() < deadline:
            record = await self._store.get_run(run_id, account_id=account_id)
            if record is None or record.status in stops:
                return record
            await asyncio.sleep(0.01)
        return await self._store.get_run(run_id, account_id=account_id)

    async def _run_loop(
        self,
        live: _LiveRun,
        *,
        initial: dict[str, Any] | None = None,
        resume: dict[str, Any] | None = None,
    ) -> None:
        """Цикл одного запуска: инвокация графа, паузы на interrupt, резюм по решению.

        Бюджет сеется из чекпойнта на каждом резюме: пределы действуют на весь запуск,
        а не на один сегмент между подтверждениями.
        """
        pump = _EventPump(self._store, live)
        live.pump = pump
        pump.start()
        budget: RunBudget | None = None
        graph: Any = None
        config: RunnableConfig | None = None
        # E-9: вызовы модели этой задачи (граф, шаг, инструменты) пишутся в llm_usage с id
        # запуска — по нему сумма токенов запуска сверяется с независимым журналом вызовов.
        attribution = set_current_agent_run_id(live.run_id)
        try:
            deps = await self._deps_factory(live.account_id)
            deps.observer = pump  # наблюдатель протокола RunObserver: узлы зовут pump.emit
            graph = build_agent_graph(deps, checkpointer=self._checkpointer)
            budget = RunBudget(deps.limits)
            config = put_budget({"configurable": {"thread_id": live.thread_id}}, budget)
            if initial is not None:
                await self._store.update_run(
                    live.run_id, account_id=live.account_id, status="running"
                )
                live.status = "running"
                pump.emit(
                    AgentEvent(
                        type="run_started",
                        payload={
                            "goal": live.goal,
                            "auto_confirm": bool(initial.get("auto_confirm")),
                            "limits": run_limits_payload(deps.limits),
                        },
                    )
                )
            else:
                await self._seed_budget(graph, config, budget)
                await self._store.update_run(
                    live.run_id, account_id=live.account_id, status="running"
                )
                live.status = "running"
            payload: Any = initial if initial is not None else Command(resume=resume)
            final: dict[str, Any] = {}
            while True:
                final = dict(await graph.ainvoke(payload, config))
                interrupts = final.get("__interrupt__") or ()
                if not interrupts:
                    break
                value = getattr(interrupts[0], "value", None)
                card = value if isinstance(value, dict) else {}
                await self._store.update_run(
                    live.run_id,
                    account_id=live.account_id,
                    status="waiting_approval",
                    usage=budget.snapshot(),
                )
                live.status = "waiting_approval"
                pump.emit(AgentEvent(type="needs_confirmation", payload={"card": card or {}}))
                decision = await live.decisions.get()
                approved = bool(decision.get("approved"))
                await self._seed_budget(graph, config, budget)
                await self._store.update_run(
                    live.run_id, account_id=live.account_id, status="running"
                )
                live.status = "running"
                edited = sorted((decision.get("edits") or {}).keys()) if approved else []
                pump.emit(
                    AgentEvent(
                        type="confirmation_resolved",
                        payload={"approved": approved, "edited": edited},
                    )
                )
                payload = Command(resume=decision)
            answer = final.get("answer")
            usage = budget.snapshot()
            await self._store.update_run(
                live.run_id,
                account_id=live.account_id,
                status="done",
                stop_reason=final.get("stop_reason"),
                answer=answer,
                usage=usage,
            )
            live.status = "done"
            pump.emit(
                AgentEvent(
                    type="done",
                    payload={
                        "answer": answer,
                        "stop_reason": final.get("stop_reason"),
                        "plan": [s.model_dump() for s in final.get("plan") or []],
                        "steps_taken": final.get("steps_taken"),
                        "pending_action": final.get("pending_action"),
                        "usage": usage,
                    },
                )
            )
        except asyncio.CancelledError:
            if not live.cancel_requested:
                raise  # остановка процесса: пауза и чекпойнт переживут рестарт
            try:
                await self._finish_cancelled(live, graph, config, pump)
            except Exception:  # noqa: BLE001 — база может быть недоступна в этот момент
                logger.exception("запуск run=%s: не записал cancelled в базу", live.run_id)
        except Exception as exc:  # noqa: BLE001 — падение задачи это failed в базе, не 500 в лог
            logger.exception("запуск run=%s упал: %s", live.run_id, exc)
            live.status = "failed"
            usage = budget.snapshot() if budget is not None else None
            try:
                await self._store.update_run(
                    live.run_id,
                    account_id=live.account_id,
                    status="failed",
                    error=str(exc),
                    usage=usage,
                )
                failed: dict[str, Any] = {"error": str(exc)}
                if usage is not None:
                    failed["usage"] = usage
                pump.emit(AgentEvent(type="failed", payload=failed))
            except Exception:  # noqa: BLE001 — база может быть недоступна в этот момент
                logger.exception("запуск run=%s: не записал failed в базу", live.run_id)
        finally:
            reset_current_agent_run_id(attribution)
            await pump.close()
            self._live.pop(live.run_id, None)

    async def cancel(self, *, run_id: int, account_id: int) -> AgentRunRecord:
        """«Стоп» (A-9): отменить запуск — идущий или ждущий подтверждения.

        Живая задача отменяется и сама пишет `cancelled` с частичным итогом по последнему
        чекпойнту. Задачи нет (пауза пережила рестарт API) — итог собирается здесь же.
        Действие, ждавшее «да», не выполняется.
        """
        record = await self._store.get_run(run_id, account_id=account_id)
        if record is None:
            raise NotFound(f"запуск {run_id} не найден")
        if record.status in ("done", "failed", "cancelled"):
            raise InvalidInput(f"запуск {run_id} уже завершён (статус {record.status})")
        live = self._live.get(run_id)
        if live is not None and live.task is not None and not live.task.done():
            live.cancel_requested = True
            live.task.cancel()
            return record
        live = _LiveRun(
            run_id=record.id,
            account_id=account_id,
            thread_id=record.thread_id,
            goal=record.goal,
            session_id=record.session_id,
            status=record.status,
        )
        pump = _EventPump(self._store, live)
        live.pump = pump
        pump.start()
        try:
            graph: Any = None
            config: RunnableConfig | None = None
            if self._checkpointer is not None:
                deps = await self._deps_factory(account_id)
                graph = build_agent_graph(deps, checkpointer=self._checkpointer)
                config = {"configurable": {"thread_id": record.thread_id}}
            await self._finish_cancelled(live, graph, config, pump)
        finally:
            await pump.close()
        return record

    async def _finish_cancelled(
        self, live: _LiveRun, graph: Any, config: RunnableConfig | None, pump: _EventPump
    ) -> None:
        """Записать `cancelled` и честный частичный итог по последнему чекпойнту."""
        values: dict[str, Any] = {}
        if graph is not None and config is not None:
            try:
                snapshot = await graph.aget_state(config)
                values = dict(snapshot.values or {})
            except Exception:  # noqa: BLE001 — нет чекпойнта: итог без сделанных шагов
                logger.warning("запуск run=%s: нет чекпойнта для итога отмены", live.run_id)
        answer = cancelled_answer(values)
        # Живой бюджет видит и вызовы после последнего чекпойнта (шаг, прерванный «Стопом»);
        # без живой задачи (пауза пережила рестарт) расход берётся из чекпойнта.
        budget = budget_from(config)
        if not budget.counting:
            budget = RunBudget(RunLimits())
            budget.restore(values)
        usage = budget.snapshot()
        live.status = "cancelled"
        await self._store.update_run(
            live.run_id,
            account_id=live.account_id,
            status="cancelled",
            stop_reason="cancelled",
            answer=answer,
            usage=usage,
        )
        pump.emit(
            AgentEvent(
                type="cancelled",
                payload={
                    "answer": answer,
                    "stop_reason": "cancelled",
                    "steps_taken": values.get("steps_taken"),
                    "usage": usage,
                },
            )
        )

    async def _seed_budget(self, graph: Any, config: RunnableConfig, budget: RunBudget) -> None:
        """Счётчики из чекпойнта в бюджет: предел продолжается, а не начинается заново."""
        try:
            snapshot = await graph.aget_state(config)
            values = snapshot.values or {}
        except Exception:  # noqa: BLE001 — нет чекпойнта: бюджет с нуля (пауза не продолжится)
            return
        budget.restore(values)


_MANAGER: AgentRunsManager | None = None


def get_runs_manager() -> AgentRunsManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = AgentRunsManager()
    return _MANAGER


def reset_runs_manager(manager: AgentRunsManager | None = None) -> AgentRunsManager:
    """Подменить синглтон (только тесты)."""
    global _MANAGER
    _MANAGER = manager or AgentRunsManager()
    return _MANAGER


async def recover_after_restart(reason: str = "прерван перезапуском API") -> int:
    """При старте API: мёртвые `running`/`queued` прошлого процесса — failed; паузы живут."""
    return await runs_repo.mark_stale_failed(reason)


__all__ = [
    "AgentRunsManager",
    "PgRunsStore",
    "RunsStore",
    "get_runs_manager",
    "recover_after_restart",
    "reset_runs_manager",
]
