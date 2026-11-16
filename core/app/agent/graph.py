"""Сборка графа агента: план → шаг → подтверждение → проверка → перестройка → финал (A-1/A-3).

Узлы как на схеме в PLAN 3: планировщик собирает план, исполнитель deepagents выполняет
шаг, узел `confirm` ставит граф на паузу, когда модель запросила действие (`queue_application`),
и ждёт «да» человека через `interrupt()` — после рестарта API запуск продолжается с того же
чекпойнта, «да» выполняет действие. Проверка шага (в A-1 — код-эвристика, модельная
самопроверка придёт в A-5), перестройка решает continue/rebuild/finish, финал отдаёт ответ
или честный частичный результат. Пределы (`RunLimits`) проверяются рёбрами между фазами;
выход за предел — остановка с частичным итогом, а не ошибка.

Наблюдатель (`AgentDeps.observer`, A-3) получает события запуска: узловые таймеры
(`node_timing`, метрика p90 шага — OQ-29) и содержательные события
(plan_created/step_started/observation/…). Без наблюдателя граф работает как раньше.

Запуск: `run_agent_goal(goal)` — считает бюджет через колбэк (`RunBudget`), поддерживает
чекпойнтер, возвращает итоговое состояние; фоновые запуски с паузой ведёт `runs.py`.
"""

from __future__ import annotations

import inspect
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from core.app.agent.budget import RunBudget, put_budget
from core.app.agent.contracts import Tool, ToolCall, ToolContext
from core.app.agent.events import AgentEvent, RunObserver, node_event
from core.app.agent.executor import step_node
from core.app.agent.planner import planner_node
from core.app.agent.replanner import replan_node
from core.app.agent.state import (
    STOP_REASONS_TEXT,
    AgentState,
    Observation,
    PlanStep,
    RunLimits,
    done_steps_summary,
    first_todo_step,
    plan_has_open_steps,
)
from core.app.agent.toolkit import execute_tool


@dataclass(slots=True)
class AgentDeps:
    """Модели и материалы графа. По умолчанию — платформенные модели по тирам.

    Тиры (решение 15.11, OQ-13): планировщик и перестройка — advanced (high effort),
    исполнитель шага — basic (low effort, скорость). Судья (A-5) добавит свой вызов.
    `observer` (A-3) — синхронный получатель событий запуска (узловые таймеры, шаги).
    """

    planner: BaseChatModel
    executor: BaseChatModel
    replanner: BaseChatModel
    limits: RunLimits = field(default_factory=RunLimits)
    tools: tuple[Tool, ...] = field(default_factory=tuple)
    tool_context: ToolContext = field(default_factory=ToolContext)
    observer: RunObserver | None = None


def default_deps(account_id: int = 1) -> AgentDeps:
    """Депенденси по умолчанию: модели по декларациям реестра, инструменты продукта (A-2).

    `account_id` — аккаунт запроса; менеджер запусков (`runs.py`) передаёт аккаунт
    владельца запуска. БД инструментов не передаётся: домены сами открывают пул.
    """
    from core.app.agent.llm import (
        AGENT_PLAN,
        AGENT_REPLAN,
        AGENT_STEP,
        ensure_agent_features_registered,
    )
    from core.app.agent.tools import TOOLS, ensure_tools_registered
    from core.platform.llm.registry import chat_model_for

    ensure_agent_features_registered()
    ensure_tools_registered()
    return AgentDeps(
        planner=chat_model_for(AGENT_PLAN, temperature=0.2),
        executor=chat_model_for(AGENT_STEP, temperature=0.2),
        replanner=chat_model_for(AGENT_REPLAN, temperature=0.2),
        tools=TOOLS,
        tool_context=ToolContext(account_id=account_id),
    )


def check_node() -> Any:
    """Узел `check` (A-1 — код-эвристика; модельная самопроверка придёт в A-5).

    Наблюдение без ошибки — шаг закрыт, доказательство уходит в план; с ошибкой — шаг
    остаётся `todo`, растёт счётчик неудач. После `max_failure_streak` неудач подряд
    ребро уводит на перестройку.
    """

    def _check(state: AgentState) -> dict[str, Any]:
        observations = state.get("observations") or []
        if not observations:
            return {}
        last = observations[-1]
        plan: list[PlanStep] = list(state.get("plan") or [])
        if last.error is None:
            evidence = last.answer or "; ".join(last.summaries) or ""
            plan = [
                (
                    s.model_copy(update={"status": "done", "result": evidence})
                    if s.id == last.step_id
                    else s
                )
                for s in plan
            ]
            return {"plan": plan, "failure_streak": 0}
        return {"failure_streak": state.get("failure_streak", 0) + 1}

    return _check


def confirm_node(base_context: ToolContext, observer: RunObserver | None, *, pausable: bool) -> Any:
    """Узел `confirm` (A-3): пауза на подтверждении действия.

    Шаг поставил карточку в `pending_action` → узел вызывает `interrupt()`: граф
    останавливается, состояние лежит в чекпойнте, менеджер запуска ждёт решения.
    «Да» — резюм с тем же чекпойнта: узел выполняет действие и дописывает наблюдение
    (последнее наблюдение — уже про результат действия, чек закроет шаг). «Нет» —
    наблюдение с ошибкой: шаг останется открытым, агент перестроится.

    Без чекпойнта пауза невозможна (нечем резюмить) — узел пропускает: карточка остаётся
    в состоянии как в A-2 (модель получает «отложено», действие не выполняется).
    """

    async def _confirm(state: AgentState) -> dict[str, Any]:
        pending = state.get("pending_action")
        if not pending:
            return {}
        if not pausable:
            return {}
        decision: Any = interrupt(
            {
                "action": str(pending.get("action", "")),
                "params": pending.get("params") or {},
                "step_id": str(pending.get("step_id") or state.get("current_step_id") or ""),
            }
        )
        approved = bool(decision.get("approved"))
        # Событие confirmation_resolved отдаёт менеджер запусков сразу после решения —
        # узел его не дублирует (второй проход узла после резюма).
        step_id = str(pending.get("step_id") or state.get("current_step_id") or "s?")
        index = int(pending.get("index") or state.get("steps_taken") or 1)
        action = str(pending.get("action", ""))
        if approved:
            # Человек сказал «да»: выполнить действие с автоподтверждением. Тот же
            # ToolContext → общие submissions, идемпотентность дублей сохраняется.
            call = ToolCall(
                id=f"{action}-approval-{index}",
                name=action,
                arguments=dict(pending.get("params") or {}),
            )
            ctx = replace(base_context, confirm=lambda _card: True)
            result, error, _ = await execute_tool(call, ctx)
            if error is None:
                summary = f"{action}: выполнено после подтверждения человеком"
            else:
                summary = f"{action}: ошибка после подтверждения — {error.message}"
            observation = Observation(
                step_id=step_id,
                index=index,
                tools=[action],
                summaries=[summary],
                error=error.message if error else None,
            )
            if observer is not None:
                observer.emit(
                    AgentEvent(
                        type="tool_called",
                        payload={
                            "step_id": step_id,
                            "index": index,
                            "tool": action,
                            "ok": error is None,
                            "summary": summary,
                            "error": error.message if error else None,
                        },
                        node="confirm",
                    )
                )
        else:
            observation = Observation(
                step_id=step_id,
                index=index,
                tools=[action],
                summaries=[f"{action}: человек отклонил действие"],
                error="человек отклонил действие — не повторяй его без явной просьбы",
            )
        if observer is not None:
            observer.emit(
                AgentEvent(type="observation", payload=observation.model_dump(), node="confirm")
            )
        return {
            "pending_action": None,
            "observations": [*(state.get("observations") or []), observation],
        }

    return _confirm


def over_budget(state: AgentState, limits: RunLimits) -> bool:
    """Бюджет запуска исчерпан: счётчики в состоянии ведут узлы по колбэку `RunBudget`."""
    calls = state.get("model_calls", 0)
    tokens = state.get("tokens_in", 0) + state.get("tokens_out", 0)
    return calls >= limits.max_model_calls or tokens >= limits.max_tokens


def derive_stop_reason(state: AgentState, limits: RunLimits) -> Any:
    """Почему остановились, если узлы не написали причину сами (порядок важный)."""
    if over_budget(state, limits):
        return "model_budget"
    if state.get("steps_taken", 0) >= limits.max_steps:
        return "step_limit"
    if state.get("replans_used", 0) >= limits.max_replans:
        return "replan_limit"
    if state.get("replan_action") == "finish":
        return "answered"  # перестройка сознательно закончила; незакрытые шаги не вина агента
    plan = state.get("plan") or []
    if plan_has_open_steps(plan):
        return "plan_exhausted"
    return "answered"


def finalize_node(limits: RunLimits) -> Any:
    """Узел `finalize`: ответ по цели или честный частичный результат (критерий A-1)."""

    def _finalize(state: AgentState) -> dict[str, Any]:
        stop = state.get("stop_reason") or derive_stop_reason(state, limits)
        answer = state.get("answer") or _compose_answer(state, stop)
        return {"answer": answer, "stop_reason": stop}

    return _finalize


def _compose_answer(state: AgentState, stop: str) -> str:
    """Текст итога: ответ модели или честный частичный (причина + что удалось + что осталось)."""
    if stop == "answered":
        observations = state.get("observations") or []
        last_answer = observations[-1].answer if observations else None
        parts = [last_answer or state.get("note") or "Цель закрыта."]
        done = done_steps_summary(state.get("plan") or [], observations)
        if done != "(шаги не закрыты)":
            parts.append(f"Что удалось:\n{done}")
        return "\n\n".join(parts)
    plan = state.get("plan") or []
    lines = [f"Не удалось закончить цель: {STOP_REASONS_TEXT.get(stop, stop)}."]
    done = done_steps_summary(plan, state.get("observations") or [])
    if done != "(шаги не закрыты)":
        lines.append(f"Что удалось:\n{done}")
    remaining = [s.title for s in plan if s.status == "todo"]
    if remaining:
        lines.append("Что осталось:\n" + "\n".join(f"- {title}" for title in remaining))
    error = state.get("error")
    if error:
        lines.append(f"Последняя ошибка: {error}")
    return "\n\n".join(lines)


def route_after_plan(state: AgentState) -> Literal["step", "finalize"]:
    """После планировщика: план готов — работаем; сбой модели — честный финал."""
    if state.get("stop_reason") is not None:
        return "finalize"
    return "step"


def route_after_step(state: AgentState) -> Literal["confirm", "finalize"]:
    """После шага: сбой модели — финал; иначе сначала подтверждение действия (A-3).

    Пределы шагов/бюджета проверяет ребро после `check`: карточка действия заслуживает
    выполнения даже на границе бюджета, а лишних вызовов модели у `confirm` нет.
    """
    if state.get("stop_reason") is not None:
        return "finalize"
    return "confirm"


def route_after_check(
    state: AgentState, limits: RunLimits
) -> Literal["step", "replan", "finalize"]:
    """После проверки: пределы — честный финал; неудачный шаг повторяется, потом перестройка."""
    if state.get("stop_reason") is not None:
        return "finalize"
    if over_budget(state, limits) or state.get("steps_taken", 0) >= limits.max_steps:
        return "finalize"
    if state.get("failure_streak", 0) > limits.max_failure_streak:
        return "replan"
    observations = state.get("observations") or []
    if observations and observations[-1].error is None:
        return "replan"  # шаг закрыт — перестройка решает, что дальше
    return "step"  # неудача: повтор того же шага


def route_after_replan(state: AgentState, limits: RunLimits) -> Literal["step", "plan", "finalize"]:
    """После перестройки: продолжаем шаги, пересобираем план или заканчиваем честно."""
    if state.get("stop_reason") is not None:
        return "finalize"
    action = state.get("replan_action")
    if action == "finish":
        return "finalize"
    if action == "rebuild":
        return "plan" if state.get("replans_used", 0) < limits.max_replans else "finalize"
    return "step"


def _after_node_event(
    name: str, state: AgentState, out: dict[str, Any], observer: RunObserver
) -> None:
    """Содержательное событие после узла, по его выходу (A-3)."""
    if name == "plan":
        plan = out.get("plan")
        if plan is not None:
            observer.emit(
                AgentEvent(
                    type="plan_created",
                    payload={"plan": [s.model_dump() for s in plan], "note": out.get("note")},
                    node=name,
                )
            )
        return
    if name == "step":
        observations = out.get("observations")
        if observations:
            observer.emit(
                AgentEvent(
                    type="observation",
                    payload=observations[-1].model_dump(),
                    node=name,
                )
            )
        return
    if name == "check":
        observations = state.get("observations") or []
        if not observations:
            return
        last: Observation = observations[-1]
        done = False
        if isinstance(out.get("plan"), list):
            done = any(s.id == last.step_id and s.status == "done" for s in out["plan"])
        observer.emit(
            AgentEvent(
                type="step_checked",
                payload={"step_id": last.step_id, "done": done, "error": last.error},
                node=name,
            )
        )
        return
    if name == "replan":
        action = out.get("replan_action")
        if action is None:
            return
        changes = out.get("plan_changes") or state.get("plan_changes") or []
        observer.emit(
            AgentEvent(
                type="plan_changed",
                payload={
                    "action": action,
                    "reason": out.get("note"),
                    "changes": changes[-1] if changes else None,
                    "plan": [s.model_dump() for s in out.get("plan") or state.get("plan") or []],
                },
                node=name,
            )
        )


def _observed_node(name: str, fn: Any, observer: RunObserver | None) -> Any:
    """Обернуть узел: таймер узла (OQ-29) и события входа/выхода, если есть наблюдатель.

    Пауза (`GraphInterrupt`) времени узла не считается — ожидание человека живёт
    снаружи графа, в менеджере запусков. Узлы с двумя позиционными параметрами получают
    config, узлы с одним — как раньше (langgraph сам разруливал арность до обёртки).
    """
    if observer is None:
        return fn

    positional = [
        p
        for p in inspect.signature(fn).parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    takes_config = len(positional) >= 2

    async def _inner(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        if name == "step":
            step = first_todo_step(state.get("plan") or [])
            if step is not None:
                observer.emit(
                    AgentEvent(
                        type="step_started",
                        payload={
                            "step_id": step.id,
                            "index": state.get("steps_taken", 0) + 1,
                            "title": step.title,
                        },
                        node=name,
                    )
                )
        started = time.perf_counter()
        try:
            out = fn(state, config) if takes_config else fn(state)
            if inspect.isawaitable(out):
                out = await out
        except GraphInterrupt:
            observer.emit(node_event(name, (time.perf_counter() - started) * 1000, paused=True))
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        observer.emit(node_event(name, elapsed_ms))
        if isinstance(out, dict):
            _after_node_event(name, state, out, observer)
        return out

    return _inner


def build_agent_graph(
    deps: AgentDeps | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Собрать граф агента. Чекпойнтер — опционально (MemorySaver в тестах, Postgres в A-3)."""
    deps = deps or default_deps()
    limits = deps.limits
    observer = deps.observer
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("plan", _observed_node("plan", planner_node(deps.planner, limits), observer))
    graph.add_node(
        "step",
        _observed_node(
            "step",
            step_node(deps.executor, deps.tools, deps.tool_context, limits, observer),
            observer,
        ),
    )
    graph.add_node(
        "confirm", confirm_node(deps.tool_context, observer, pausable=checkpointer is not None)
    )
    graph.add_node("check", _observed_node("check", check_node(), observer))
    graph.add_node("replan", _observed_node("replan", replan_node(deps.replanner), observer))
    graph.add_node("finalize", finalize_node(limits))
    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {"step": "step", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "step",
        route_after_step,
        {"confirm": "confirm", "finalize": "finalize"},
    )
    graph.add_edge("confirm", "check")
    graph.add_conditional_edges(
        "check",
        lambda s: route_after_check(s, limits),
        {"step": "step", "replan": "replan", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "replan",
        lambda s: route_after_replan(s, limits),
        {"plan": "plan", "step": "step", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


async def run_agent_goal(
    goal: str,
    *,
    deps: AgentDeps | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    thread_id: str | None = None,
    config: RunnableConfig | None = None,
) -> AgentState:
    """Прогнать цель через граф и вернуть итоговое состояние.

    Бюджет одного запуска считается колбэком `RunBudget` (вызовы модели и токены,
    включая вызовы внутри шага deepagents); с чекпойнтером нужен `thread_id` —
    тогда состояние переживает паузу (A-3).
    """
    resolved_deps = deps or default_deps()
    budget = RunBudget(resolved_deps.limits)
    incoming: RunnableConfig = {**(config or {})}
    configurable = {**(incoming.get("configurable") or {})}
    configurable["thread_id"] = thread_id or f"agent-{uuid.uuid4().hex[:12]}"
    base: RunnableConfig = {**incoming, "configurable": configurable}
    graph = build_agent_graph(resolved_deps, checkpointer=checkpointer)
    final = await graph.ainvoke({"goal": goal}, config=put_budget(base, budget))
    return final  # type: ignore[return-value]


__all__ = [
    "AgentDeps",
    "build_agent_graph",
    "check_node",
    "confirm_node",
    "default_deps",
    "derive_stop_reason",
    "finalize_node",
    "over_budget",
    "route_after_check",
    "route_after_plan",
    "route_after_replan",
    "route_after_step",
    "run_agent_goal",
]
