"""Исполнитель шага на deepagents и его профиль под наши модели (A-1).

deepagents — каркас шага (решение по OQ-5): внутри шага маленький ReAct на
`create_deep_agent`, снаружи — наши узлы графа. Свои надстройки deepagents режутся
профилем harness: инструменты рабочей папки (`ls`, `read_file`, …) и встроенный
субагент «общего назначения» исполнителю шага не показываются — у шага доменные
инструменты из `agent/` (замер P0-4: держать 3–6 инструментов на шаг) плюс наш
`task` для двух субагентов курса (A-8, OQ-28; роли и лимиты — `subagents.py`).

Профиль привязывается к провайдеру модели (`ls_provider = "openrouter"`), поэтому
действует и для GLM, и для быстрого маршрута, и для фейков тестов, если те рапортуют
тот же провайдер.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    SubAgent,
    create_deep_agent,
    register_harness_profile,
)
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

_PROFILE_KEY = "openrouter"
"""Ключ профиля: совпадает с `ls_provider` у `OpenRouterChatModel` (см. там `_get_ls_params`)."""

_EXCLUDED_BUILTINS = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep"}
)
"""Инструменты deepagents, которые шагу не нужны: рабочая папка.

`task` не вырезается с A-8: субагенты курса (исследователь страны и оценщик
вакансий) вызываются из узла шага как `task` (OQ-28). Без `subagents=` инструмент
`task` всё равно не появляется — deepagents добавляет его только вместе с субагентами.
"""


def register_course_profile() -> None:
    """Зарезать built-ins deepagents для всех моделей провайдера (идемпотентно,
    повторная регистрация deepagents сливает профили)."""
    register_harness_profile(
        _PROFILE_KEY,
        HarnessProfile(
            excluded_tools=_EXCLUDED_BUILTINS,
            general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False),
        ),
    )


def build_step_agent(
    *,
    model: BaseChatModel,
    tools: Sequence[BaseTool],
    system_prompt: str,
    subagents: Sequence[SubAgent] | None = None,
    middleware: Sequence[AgentMiddleware] = (),
) -> CompiledStateGraph:
    """Скомпилировать исполнителя одного шага: модель, доменные инструменты, промпт.

    `subagents` (A-8) объявляет роли инструмента `task`; `middleware` — наши
    надстройки над шагом (`SubagentGate`). Чекпойнтер у внутреннего графа не ставится:
    состояние шага живёт внутри вызова, на pause/resume смотрит внешний граф (A-3)
    со своим чекпойнтером.
    """
    register_course_profile()
    kwargs: dict[str, Any] = {}
    if subagents:
        kwargs["subagents"] = list(subagents)
    if middleware:
        kwargs["middleware"] = list(middleware)
    return create_deep_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        name="course_step_agent",
        **kwargs,
    )


__all__ = ["build_step_agent", "register_course_profile"]
