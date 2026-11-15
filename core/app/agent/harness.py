"""Исполнитель шага на deepagents и его профиль под наши модели (A-1).

deepagents — каркас шага (решение по OQ-5): внутри шага маленький ReAct на
`create_deep_agent`, снаружи — наши узлы графа. Свои надстройки deepagents режутся
профилем harness: инструменты рабочей папки (`ls`, `read_file`, …), `task` и встроенный
субагент «общего назначения» исполнителю шага не показываются — у шага только доменные
инструменты из `agent/` (замер P0-4: держать 3–6 инструментов на шаг).

Профиль привязывается к провайдеру модели (`ls_provider = "openrouter"`), поэтому
действует и для GLM, и для быстрого маршрута, и для фейков тестов, если те рапортуют
тот же провайдер.
"""

from __future__ import annotations

from collections.abc import Sequence

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

_PROFILE_KEY = "openrouter"
"""Ключ профиля: совпадает с `ls_provider` у `OpenRouterChatModel` (см. там `_get_ls_params`)."""

_EXCLUDED_BUILTINS = frozenset(
    {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "task"}
)
"""Инструменты deepagents, которые шагу не нужны: рабочая папка и вызов субагентов.

Субагенты (OQ-28, A-8) добавляются позже отдельными ролями с коротким промптом,
а не встроенным «общего назначения».
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
) -> CompiledStateGraph:
    """Скомпилировать исполнителя одного шага: модель, доменные инструменты, промпт шага.

    Чекпойнтер у внутреннего графа не ставится: состояние шага живёт внутри вызова,
    на pause/resume смотрит внешний граф (A-3) со своим чекпойнтером.
    """
    register_course_profile()
    return create_deep_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        name="course_step_agent",
    )


__all__ = ["build_step_agent", "register_course_profile"]
