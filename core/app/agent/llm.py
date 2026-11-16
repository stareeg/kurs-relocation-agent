"""LLM-фичи узлов агента: декларации реестра рядом с кодом агента (A-1, A-8, A-5).

Реестр `core.platform.llm.registry` живёт декларациями в `domains/*/llm.py`, но платформа
не импортирует слой приложения — поэтому агентные фичи регистрируются явным
`ensure_agent_features_registered()` (зовёт `default_deps` при сборке графа по умолчанию).

Тиры и усилия — по решениям 15.11 (OQ-13) и 16.11 (OQ-28): планировщик и перестройка —
advanced/high, исполнитель шага и оба субагента — basic/low (скорость, локальные задачи).
Судья (A-5, OQ-21) — модель другой семьи, тир `reserve` (DeepSeek V4.1 Flash через
OpenRouter): проверка шага — low (потолок 2048, 90 с), судья итога — high (потолок
4096, 240 с, короткий вход); у обоих temperature 0. budget_ms у шага и субагентов
шире: внутри одного вызова deepagents делает несколько обращений к модели.
"""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

AGENT_PLAN = "agent_plan"
AGENT_STEP = "agent_step"
AGENT_REPLAN = "agent_replan"
AGENT_SUB_COUNTRY = "agent_sub_country"
AGENT_SUB_VACANCY = "agent_sub_vacancy"
AGENT_JUDGE_STEP = "agent_judge_step"
AGENT_JUDGE_FINAL = "agent_judge_final"


def ensure_agent_features_registered() -> None:
    """Зарегистрировать фичи агента (идемпотентно: повтор с тем же содержимым — ok)."""
    from core.app.agent.judge import JudgeSpec
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
    # Субагенты шага (A-8, OQ-28): обе роли basic/low — локальная задача и короткий
    # промпт; возвращаетPydantic-схему с цитатами (все поля required — правило GLM).
    register(
        LlmFeature(
            name=AGENT_SUB_COUNTRY,
            tier="basic",
            prompt="prompts/agent/sub_research_country.md",
            max_tokens=2048,
            budget_ms=120_000,
            reasoning_effort="low",
        )
    )
    register(
        LlmFeature(
            name=AGENT_SUB_VACANCY,
            tier="basic",
            prompt="prompts/agent/sub_assess_vacancies.md",
            max_tokens=2048,
            budget_ms=120_000,
            reasoning_effort="low",
        )
    )
    # Судья (A-5, OQ-21): модель другой семьи (reserve — DeepSeek V4.1 Flash через
    # OpenRouter), температура 0, формат {reason, verdict} — причина первой.
    register(
        LlmFeature(
            name=AGENT_JUDGE_STEP,
            tier="reserve",
            prompt="prompts/agent/judge.md",
            schema=JudgeSpec,
            max_tokens=2048,
            budget_ms=90_000,
            temperature=0.0,
            reasoning_effort="low",
        )
    )
    register(
        LlmFeature(
            name=AGENT_JUDGE_FINAL,
            tier="reserve",
            prompt="prompts/agent/judge.md",
            schema=JudgeSpec,
            max_tokens=4096,
            budget_ms=240_000,
            temperature=0.0,
            reasoning_effort="high",
        )
    )


__all__ = [
    "AGENT_JUDGE_FINAL",
    "AGENT_JUDGE_STEP",
    "AGENT_PLAN",
    "AGENT_REPLAN",
    "AGENT_STEP",
    "AGENT_SUB_COUNTRY",
    "AGENT_SUB_VACANCY",
    "ensure_agent_features_registered",
]
