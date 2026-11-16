"""Исполнитель шага (узел `step`): маленький ReAct внутри шага на deepagents (A-1).

Каждый запуск шага — отдельный вызов внутреннего графа deepagents: в системном промпте
цель, перечитанный план и текущий шаг; инструменты — обёртки контрактов из `agent/`
(см. `tools.py`). История шага в состояние не тащится: только сводки наблюдений.
Предел ходов внутри шага — `recursion_limit` внутреннего графа (`RunLimits`).
"""

from __future__ import annotations

from typing import Any, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from core.app.agent.budget import budget_from
from core.app.agent.contracts import Tool, ToolContext
from core.app.agent.events import RunObserver
from core.app.agent.harness import build_step_agent
from core.app.agent.prompts import load_prompt
from core.app.agent.state import (
    AgentState,
    Observation,
    RunLimits,
    first_todo_step,
    render_plan,
)
from core.app.agent.subagents import build_subagent_specs
from core.app.agent.tools import StepRecorder, build_run_context, to_langchain_tools


def build_step_system(state: AgentState) -> str:
    """Системный промпт шага: правила из файла + цель + перечитанный план."""
    parts = [
        load_prompt("step"),
        f"## Цель\n{state['goal']}",
        f"## План\n{render_plan(state['plan'])}",
    ]
    note = state.get("note")
    if note:
        parts.append(f"## Как цель понята\n{note}")
    return "\n\n".join(parts)


def step_user_task(state: AgentState) -> str:
    """Задание текущего шага одним текстом."""
    step = first_todo_step(state["plan"])
    assert step is not None  # узел вызывается, только когда есть незакрытый шаг
    return f"Выполни шаг {step.id}: {step.title}.\nКритерий выполнения: {step.done_criteria}."


def final_text_of(messages: list[BaseMessage]) -> str | None:
    """Финальный текст шага: последний AIMessage без инструментальных вызовов."""
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not message.tool_calls and message.content:
            content = message.content
            if isinstance(content, str):
                return content
            return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return None


def step_node(
    model: BaseChatModel,
    tools: tuple[Tool, ...],
    base_context: ToolContext,
    limits: RunLimits,
    observer: RunObserver | None = None,
    subagent_models: dict[str, BaseChatModel] | None = None,
) -> Any:
    """Узел `step`: собрать исполнителя deepagents на текущий шаг и выполнить его.

    `observer` (A-3) получает события шага: tool_called на каждый вызов инструмента.
    `subagent_models` (A-8, OQ-28) объявляет субагентов инструмента `task`:
    исследователь страны и оценщик вакансий, лимит вызовов — `RunLimits.
    max_subagent_calls`; вызовы модели субагентов считает тот же бюджет запуска.
    """

    async def _step(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        step = first_todo_step(state["plan"])
        if step is None:
            return {"stop_reason": "plan_exhausted"}
        index = state.get("steps_taken", 0) + 1
        recorder = StepRecorder(step.id, index, emit=observer)
        ctx = build_run_context(base_context, recorder)
        extra_middleware: list[Any] = []
        subagent_specs = None
        if subagent_models:
            subagent_specs, gate = build_subagent_specs(
                subagent_models, ctx, recorder, limits, observer
            )
            extra_middleware.append(gate)
        agent: CompiledStateGraph = build_step_agent(
            model=model,
            tools=to_langchain_tools(tools, ctx, recorder),
            system_prompt=build_step_system(state),
            subagents=subagent_specs,
            middleware=extra_middleware,
        )
        run_config: dict[str, Any] = {
            **(config or {}),
            "recursion_limit": limits.step_recursion_limit,
        }
        try:
            out = await agent.ainvoke(
                {"messages": [HumanMessage(content=step_user_task(state))]},
                config=cast("RunnableConfig", run_config),
            )
        except Exception as exc:  # noqa: BLE001 — сбой шага это наблюдение с ошибкой, не падение графа
            recorder.summaries.append(f"шаг прерван: {exc}")
            recorder.last_error = recorder.last_error or str(exc)
            answer = None
        else:
            answer = final_text_of(list(out["messages"]))
        budget = budget_from(config)
        observation: Observation = recorder.to_observation(answer)
        pending: dict[str, Any] | None = (
            {
                "action": recorder.pending.action,
                "params": recorder.pending.params,
                "step_id": step.id,
                "index": index,
            }
            if recorder.pending
            else state.get("pending_action")
        )
        return {
            "current_step_id": step.id,
            "steps_taken": index,
            "observations": [*(state.get("observations") or []), observation],
            "vacancies": [*(state.get("vacancies") or []), *recorder.vacancies],
            "pending_action": pending,
            **budget.state_update(),
        }

    return _step


__all__ = ["build_step_system", "final_text_of", "step_node", "step_user_task"]
