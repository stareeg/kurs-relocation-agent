"""Агент курса: минимальный ReAct-цикл с инструментами (ДЗ1).

Слой стоит отдельно от продукта и не импортирует `core`: его задача — показать контракты
инструментов, лимит шагов, подтверждение действий и смену провайдера конфигом. Доменные
инструменты продукта подключаются сюда в A-2, когда цикл будет встроен в сервис.
"""

from agent.config import AgentConfig
from agent.contracts import AgentRun, ConfirmationCard, Step, ToolCall, ToolContext, ToolError
from agent.loop import run_agent
from agent.providers import OpenAICompatProvider, Provider, ProviderTurn, ScriptedProvider
from agent.tools import TOOLS, execute_tool, tool_by_name

__all__ = [
    "AgentConfig",
    "AgentRun",
    "ConfirmationCard",
    "OpenAICompatProvider",
    "Provider",
    "ProviderTurn",
    "ScriptedProvider",
    "Step",
    "TOOLS",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "execute_tool",
    "run_agent",
    "tool_by_name",
]
