"""Провайдер и модель агента — только из окружения, как требует курс.

Код один, меняются три переменные: `AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY`.
Так агент переезжает между GigaChat, GLM, Groq и OpenRouter без правок кода.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL = "glm-5.3-flash"
DEFAULT_BASE_URL = "http://litellm:4000/v1"
DEFAULT_TIMEOUT_S = 120.0


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """Что нужно агенту для вызова модели. Ключ в репозиторий не попадает."""

    base_url: str
    model: str
    api_key: str
    provider: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_steps: int = 6
    # Необязательное усилие размышлений: GLM понимает low/high, GigaChat — нет.
    reasoning_effort: str | None = None

    @classmethod
    def from_env(cls) -> AgentConfig:
        """Собрать конфиг из окружения. Без ключа дальше работать нельзя — падаем сразу."""
        api_key = os.environ.get("AGENT_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "AGENT_API_KEY не задан. Провайдер и модель меняются в конфиге: "
                "AGENT_BASE_URL, AGENT_MODEL, AGENT_API_KEY (см. README, раздел «Агент»)"
            )
        base_url = os.environ.get("AGENT_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        model = os.environ.get("AGENT_MODEL", DEFAULT_MODEL).strip()
        provider = os.environ.get("AGENT_PROVIDER", "").strip() or model.split("/")[0]
        timeout = float(os.environ.get("AGENT_TIMEOUT_S", DEFAULT_TIMEOUT_S))
        max_steps = int(os.environ.get("AGENT_MAX_STEPS", "6"))
        effort = os.environ.get("AGENT_REASONING_EFFORT", "").strip() or None
        return cls(
            base_url=base_url,
            model=model,
            api_key=api_key,
            provider=provider,
            timeout_s=timeout,
            max_steps=max_steps,
            reasoning_effort=effort,
        )
