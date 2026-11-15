"""Сборка графа агента: план → шаг → проверка → перестройка → финал (A-1).

Узлы как на схеме в PLAN 3: планировщик собирает план, исполнитель deepagents выполняет
шаг, проверка шага (в A-1 — код-эвристика, модельная самопроверка придёт в A-5),
перестройка решает continue/rebuild/finish, финал отдаёт ответ или честный частичный
результат. Пределы (`RunLimits`) проверяются рёбрами между фазами; выход за предел —
остановка с частичным итогом, а не ошибка.

Запуск: `run_agent_goal(goal)` — считает бюджет через колбэк (`RunBudget`), поддерживает
чекпойнтер, возвращает итоговое состояние.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.contracts import Tool, ToolContext
from core.app.agent.budget import RunBudget, put_budget
from core.app.agent.executor import step_node
from core.app.agent.planner import planner_node
from core.app.agent.replanner import replan_node
from core.app.agent.state import (
    STOP_REASONS_TEXT,
    AgentState,
    PlanStep,
    RunLimits,
    done_steps_summary,
    plan_has_open_steps,
)


@dataclass(slots=True)
class AgentDeps:
    """Модели и материалы графа. По умолчанию — платформенные модели по тирам.

    Тиры (решение 15.11, OQ-13): планировщик и перестройка — advanced (high effort),
    исполнитель шага — basic (low effort, скорость). Судья (A-5) добавит свой вызов.
    """

    planner: BaseChatModel
    executor: BaseChatModel
    replanner: BaseChatModel
    limits: RunLimits = field(default_factory=RunLimits)
    tools: tuple[Tool, ...] = field(default_factory=tuple)
    tool_context: ToolContext = field(default_factory=ToolContext)


def default_deps() -> AgentDeps:
    """Депенденси по умолчанию: модели по декларациям реестра, инструменты ДЗ1."""
    from agent.tools import TOOLS
    from core.app.agent.llm import (
        AGENT_PLAN,
        AGENT_REPLAN,
        AGENT_STEP,
        ensure_agent_features_registered,
    )
    from core.platform.llm.registry import chat_model_for

    ensure_agent_features_registered()
    return AgentDeps(
        planner=chat_model_for(AGENT_PLAN, temperature=0.2),
        executor=chat_model_for(AGENT_STEP, temperature=0.2),
        replanner=chat_model_for(AGENT_REPLAN, temperature=0.2),
        tools=TOOLS,
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


def route_after_step(state: AgentState, limits: RunLimits) -> Literal["check", "finalize"]:
    """После шага: предел или бюджет исчерпаны — финал; иначе проверка шага."""
    if state.get("stop_reason") is not None:
        return "finalize"
    if over_budget(state, limits) or state.get("steps_taken", 0) >= limits.max_steps:
        return "finalize"
    return "check"


def route_after_check(state: AgentState, limits: RunLimits) -> Literal["step", "replan"]:
    """После проверки: неудачный шаг повторяется, пока не кончатся повторы, потом перестройка."""
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


def build_agent_graph(
    deps: AgentDeps | None = None,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Собрать граф агента. Чекпойнтер — опционально (MemorySaver в тестах, Postgres в A-3)."""
    deps = deps or default_deps()
    limits = deps.limits
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("plan", planner_node(deps.planner, limits))
    graph.add_node("step", step_node(deps.executor, deps.tools, deps.tool_context, limits))
    graph.add_node("check", check_node())
    graph.add_node("replan", replan_node(deps.replanner))
    graph.add_node("finalize", finalize_node(limits))
    graph.add_edge(START, "plan")
    graph.add_conditional_edges(
        "plan",
        route_after_plan,
        {"step": "step", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "step",
        lambda s: route_after_step(s, limits),
        {"check": "check", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "check",
        lambda s: route_after_check(s, limits),
        {"step": "step", "replan": "replan"},
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
