"""LLM-фичи узлов агента: декларации реестра рядом с кодом агента (A-1).

Реестр `core.platform.llm.registry` живёт декларациями в `domains/*/llm.py`, но платформа
не импортирует слой приложения — поэтому агентные фичи регистрируются явным
`ensure_agent_features_registered()` (зовёт `default_deps` при сборке графа по умолчанию).

Тиры и усилия — по решениям 15.11 (OQ-13): планировщик и перестройка — advanced/high,
исполнитель шага — basic/low (скорость, маленький ReAct). budget_ms у шага шире:
внутри одного шага deepagents делает несколько вызовов модели.
"""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

AGENT_PLAN = "agent_plan"
AGENT_STEP = "agent_step"
AGENT_REPLAN = "agent_replan"


def ensure_agent_features_registered() -> None:
    """Зарегистрировать фичи агента (идемпотентно: повтор с тем же содержимым — ok)."""
    from core.app.agent.planner import PlanSpec
    from core.app.agent.replanner import ReplanSpec

    register(
        LlmFeature(
            name=AGENT_PLAN,
            tier="advanced",
            prompt="prompts/agent/plan.md",
            schema=PlanSpec,
            max_tokens=2048,
            budget_ms=45_000,
            reasoning_effort="high",
        )
    )
    register(
        LlmFeature(
            name=AGENT_STEP,
            tier="basic",
            prompt="prompts/agent/step.md",
            max_tokens=3072,
            budget_ms=90_000,
            reasoning_effort="low",
        )
    )
    register(
        LlmFeature(
            name=AGENT_REPLAN,
            tier="advanced",
            prompt="prompts/agent/replan.md",
            schema=ReplanSpec,
            max_tokens=2048,
            budget_ms=45_000,
            reasoning_effort="high",
        )
    )


__all__ = ["AGENT_PLAN", "AGENT_REPLAN", "AGENT_STEP", "ensure_agent_features_registered"]
