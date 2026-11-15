"""Провайдеры модели: живой OpenAI-совместимый и записанный (для тестов и офлайн-демо).

Один и тот же цикл работает с любым провайдером: меняется только конфиг
(`AGENT_BASE_URL`, `AGENT_MODEL`, `AGENT_API_KEY`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from agent.contracts import ToolCall


@dataclass(slots=True)
class ProviderTurn:
    """Ответ модели: либо текст, либо просьба о вызовах инструментов (или оба)."""

    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tokens_in: int = 0
    tokens_out: int = 0

    def as_message(self) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": call.arguments
                        if isinstance(call.arguments, str)
                        else json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in self.tool_calls
            ]
        return message


def _arguments(raw: object) -> str | dict[str, Any]:
    """Аргументы от провайдера — строка JSON; разбираем, чтобы журнал и проверки были читаемы.

    Если JSON битый, отдаём строку как есть: `execute_tool` вернёт модели ошибку валидации.
    """
    if not isinstance(raw, str):
        return raw if isinstance(raw, dict) else "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return parsed if isinstance(parsed, dict) else raw


class Provider(Protocol):
    name: str

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ProviderTurn: ...


@dataclass(slots=True)
class OpenAICompatProvider:
    """GigaChat, GLM, Groq, OpenRouter — все через один `/chat/completions`."""

    base_url: str
    model: str
    api_key: str
    timeout_s: float = 120.0
    temperature: float = 0.2
    reasoning_effort: str | None = None
    name: str = "openai-compatible"
    _client: httpx.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(timeout=self.timeout_s)

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderTurn:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=body,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"провайдер {self.model} ответил {response.status_code}: {response.text[:300]}"
            )
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = tuple(
            ToolCall(
                id=str(call.get("id") or f"call_{index}"),
                name=str((call.get("function") or {}).get("name") or ""),
                arguments=_arguments((call.get("function") or {}).get("arguments")),
            )
            for index, call in enumerate(message.get("tool_calls") or (), start=1)
        )
        usage = data.get("usage") or {}
        return ProviderTurn(
            content=message.get("content"),
            tool_calls=calls,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )


@dataclass(slots=True)
class ScriptedProvider:
    """Записанные ответы по порядку. Нужен для тестов и демо без сети и без ключа."""

    turns: list[ProviderTurn]
    name: str = "scripted"

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ProviderTurn:
        _ = (messages, tools)
        if not self.turns:
            return ProviderTurn(content="Сценарий закончился: живых ответов больше нет.")
        return self.turns.pop(0)
