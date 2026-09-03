"""IntegrationSettings — внешние системы (.env: LANGSMITH_*).

Единственная живая интеграция — трассировка LangSmith (`core.platform.observability.langsmith`,
включается флагом `LANGSMITH_TRACING`). Всё остальное подключается напрямую в своих модулях:
OpenRouter — `LlmSettings`, Telegram — `bot_app.config`.
"""

from __future__ import annotations

from pydantic import BaseModel


class IntegrationSettings(BaseModel):
    """Сторонние интеграции."""

    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_api_key_path: str = "secrets/langsmith-api-key.md"
    langsmith_project: str = "copilot"
    langsmith_endpoint: str = "https://api.smith.langchain.com"


__all__ = ["IntegrationSettings"]
