"""Планировщик: цель → план (A-1, узел `plan`).

Structured-вызов платформенным путём (`_StructuredOutputRunnable`: response_format=json_schema
+ Pydantic-валидация с одним ремонтным вызовом, канон L-13). План пишется в состояние;
тот же узел собирает план заново при перестройке — тогда в вводе есть накопленные
наблюдения и прежний план.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from core.app.agent.budget import budget_from
from core.app.agent.prompts import load_prompt
from core.app.agent.state import AgentState, PlanStep, RunLimits, render_plan
from core.platform.llm.openrouter_chat import _StructuredOutputRunnable


class PlanStepSpec(BaseModel):
    """Шаг плана от модели. Все поля обязательны: строгая схема для GLM (замер P0-4)."""

    id: str = Field(description="короткий id шага, s1, s2, …")
    title: str = Field(description="короткое название шага, глагол + объект")
    done_criteria: str = Field(description="по какому признаку шаг считается выполненным")


class PlanSpec(BaseModel):
    """Structured-выход планировщика."""

    steps: list[PlanStepSpec] = Field(description="план из 3–6 шагов по порядку")
    note: str = Field(description="одной фразой, как ты понял цель")


def clamp_plan_steps(spec: PlanSpec, limits: RunLimits) -> list[PlanStep]:
    """Шаги из ответа модели с мягкой обрезкой по пределам плана."""
    unique: dict[str, PlanStep] = {}
    for i, item in enumerate(spec.steps, start=1):
        step_id = item.id.strip() or f"s{i}"
        unique.setdefault(
            step_id, PlanStep(id=step_id, title=item.title, done_criteria=item.done_criteria)
        )
    return list(unique.values())[: limits.plan_max_steps]


def judge_remark(state: AgentState) -> str | None:
    """Замечание судьи итога (A-5) для планировщика: почему итог не принят."""
    verdict = state.get("judge_verdict") or {}
    if verdict.get("level") != "final" or verdict.get("verdict") != "fail":
        return None
    lines = [str(verdict.get("reason") or "итог не принят")]
    failures = verdict.get("quote_failures") or []
    if failures:
        lines.append("цитаты вывода, которых нет в материалах: " + "; ".join(map(str, failures)))
    return "\n".join(lines)


def planner_node(model: BaseChatModel, limits: RunLimits) -> Any:
    """Узел `plan`: structured-запрос плана; план и понимание цели — в состояние."""

    async def _planner(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        parts = [load_prompt("plan"), f"## Цель\n{state['goal']}"]
        remark = judge_remark(state)
        if remark:
            # Судья отправил итог на доработку (A-5): план должен закрыть пробелы
            # и закончиться шагом-выводом с опорой-цитатой.
            parts.append("## Замечание судьи (итог не принят, собери план доработки)\n" + remark)
        observations = state.get("observations") or []
        if observations:
            parts.append(
                "## Что уже известно\n"
                + "\n".join(o.answer or "; ".join(o.summaries) or "-" for o in observations)
            )
        current_plan = state.get("plan") or []
        if current_plan:
            parts.append(
                "## Текущий план (собирается заново после перестройки)\n"
                + render_plan(current_plan)
            )

        messages = [
            SystemMessage(content="\n\n".join(parts)),
            HumanMessage(content="Составь план по цели."),
        ]
        try:
            spec = await _StructuredOutputRunnable(model, PlanSpec, max_retries=1).ainvoke(
                messages, config=config
            )
        except Exception as exc:  # noqa: BLE001 — сбой модели это stop_reason, а не падение графа
            budget = budget_from(config)
            return {
                "error": f"планировщик: {exc}",
                "stop_reason": "model_error",
                **budget.state_update(),
            }
        budget = budget_from(config)
        return {
            "plan": clamp_plan_steps(spec, limits),
            "note": spec.note,
            **budget.state_update(),
        }

    return _planner


__all__ = [
    "PlanSpec",
    "PlanStepSpec",
    "clamp_plan_steps",
    "judge_remark",
    "planner_node",
]
