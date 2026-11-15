"""Перестройка плана (узел `replan`): план верен? поменяй? закончи? (A-1, OQ-6).

Structured-вызов тем же платформенным путём, что и планировщик. Статусы шагов правятся
по id; «было/стало» пишется в `plan_changes` для экрана (A-4). Перестройка решений
о Judge не принимает — судьёй становится отдельный узел в A-5; здесь `finish` значит
«цель покрыта собранными фактами, останавливаемся честно».
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from core.app.agent.budget import budget_from
from core.app.agent.prompts import load_prompt
from core.app.agent.state import (
    AgentState,
    Observation,
    apply_replan,
    plan_diff,
    render_plan,
)
from core.platform.llm.openrouter_chat import _StructuredOutputRunnable


class PlanStepUpdate(BaseModel):
    """Актуальное состояние шага от перестройки. Все поля обязательны (схема для GLM)."""

    id: str = Field(description="id шага из текущего плана, s1, s2…")
    title: str = Field(description="короткое название шага")
    done_criteria: str = Field(description="признак выполнения шага")
    status: Literal["todo", "done", "dropped"] = Field(description="актуальный статус шага")


class ReplanSpec(BaseModel):
    """Structured-выход перестройки: решение и актуальный план целиком."""

    action: Literal["continue", "rebuild", "finish"] = Field(
        description=(
            "continue — план верен; rebuild — план неверен, соберёт планировщик; "
            "finish — цель покрыта"
        )
    )
    reason: str = Field(description="одно предложение: почему такое решение")
    steps: list[PlanStepUpdate] = Field(
        description="актуальный план целиком; пустой список при rebuild"
    )


def replan_inputs(state: AgentState) -> str:
    """Что перестройка читает: цель, план, последнее наблюдение, счётчики."""
    observations = state.get("observations") or []
    last_obs: Observation | None = observations[-1] if observations else None
    last = (
        f"инструменты: {', '.join(last_obs.tools) or '—'}; ошибки: {last_obs.error or 'нет'}; "
        f"итог: {last_obs.answer or '; '.join(last_obs.summaries) or '—'}"
        if last_obs
        else "—"
    )
    streak = state.get("failure_streak", 0)
    return (
        f"## Цель\n{state['goal']}\n\n## План\n{render_plan(state['plan'])}\n\n"
        f"## Последнее наблюдение\n{last}\n\n"
        f"## Счётчики\nшагов исполнено: {state.get('steps_taken', 0)}; "
        f"подряд неудач: {streak}; перестроек: {state.get('replans_used', 0)}"
    )


def replan_node(model: BaseChatModel) -> Any:
    """Узел `replan`: решение и правка плана; diff «было/стало» — в состояние."""

    async def _replan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        messages = [
            SystemMessage(content=load_prompt("replan")),
            HumanMessage(content=replan_inputs(state)),
        ]
        try:
            spec = await _StructuredOutputRunnable(model, ReplanSpec, max_retries=1).ainvoke(
                messages, config=config
            )
        except Exception as exc:  # noqa: BLE001 — сбой модели это stop_reason, а не падение графа
            budget = budget_from(config)
            return {
                "error": f"перестройка: {exc}",
                "stop_reason": "model_error",
                "model_calls": budget.calls,
                "tokens_in": budget.tokens_in,
                "tokens_out": budget.tokens_out,
            }
        budget = budget_from(config)
        # Предел перестроек считает только реальные правки плана: решение «continue»
        # после каждого шага — это нормальный ход, а не перестройка.
        rebuilds = 1 if spec.action == "rebuild" else 0
        base: dict[str, Any] = {
            "replan_action": spec.action,
            "replans_used": state.get("replans_used", 0) + rebuilds,
            "model_calls": budget.calls,
            "tokens_in": budget.tokens_in,
            "tokens_out": budget.tokens_out,
        }
        if spec.action == "rebuild":
            return {**base, "note": spec.reason}
        if spec.action == "finish":
            # Финал не правит план: статусы уже в состоянии, ответ соберёт финализация.
            return {**base, "note": spec.reason}
        before = state.get("plan") or []
        after = apply_replan(before, [s.model_dump() for s in spec.steps])
        return {
            **base,
            "plan": after,
            "plan_changes": [*(state.get("plan_changes") or []), plan_diff(before, after)],
        }

    return _replan


__all__ = ["ReplanSpec", "replan_inputs", "replan_node"]
