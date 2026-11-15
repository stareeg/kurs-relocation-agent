"""Контракты инструментов и данные, которые ходят через цикл.

Восемь полей контракта (требование семинара): имя, описание, аргументы, что не от модели,
результат, ошибки, тип (чтение/действие), отказ. Здесь они разложены по классам: `Tool`
описывает первые три и последние три, `ToolContext` — то, что код знает сам, `ToolError` —
формат ошибки.
"""

from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel


class ToolError(BaseModel):
    """Ошибка инструмента уходит модели как обычный результат, а не исключение."""

    type: Literal["validation", "not_found", "no_permission", "timeout", "unavailable", "busy"]
    message: str
    hint: str = ""


@dataclass(slots=True)
class ConfirmationCard:
    """Карточка подтверждения: человек видит действие и ровно те параметры, что исполнит код."""

    action: str
    params: dict[str, Any]


@dataclass(slots=True)
class ToolContext:
    """То, что код знает сам и модель выбирать не должна (сессия клиента, права, сбои)."""

    applicant_id: str = "applicant_demo"
    citizenship: str = "RU"
    faults: dict[str, deque[str]] = field(default_factory=dict)
    confirm: Callable[[ConfirmationCard], bool] | None = None
    submissions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def take_fault(self, tool: str) -> str | None:
        """Запланированный сбой для демо: «инструмент вернул ошибку» без сети."""
        queue = self.faults.get(tool)
        return queue.popleft() if queue else None


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Просьба модели о вызове. `arguments` — уже разобранный JSON или сырая строка."""

    id: str
    name: str
    arguments: str | dict[str, Any]


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    kind: Literal["read", "action"]
    fn: Callable[[BaseModel, ToolContext], dict[str, Any]]
    requires_confirmation: bool = False

    def schema(self) -> dict[str, Any]:
        params = self.args_model.model_json_schema()
        params.setdefault("additionalProperties", False)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": params,
            },
        }


@dataclass(slots=True)
class Step:
    """Одна запись журнала: что предложила модель, чем это кончилось, кто подтвердил."""

    index: int
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]
    error: ToolError | None = None
    confirmed_by: str | None = None

    def as_log(self) -> dict[str, Any]:
        return {
            "step": self.index,
            "tool": self.tool,
            "args": self.args,
            "error": self.error.type if self.error else None,
            "confirmed_by": self.confirmed_by,
        }


@dataclass(slots=True)
class AgentRun:
    """Итог прогона: ответ, журнал шагов, потраченные токены и причина остановки."""

    answer: str | None
    steps: list[Step]
    stop_reason: Literal["answered", "step_limit", "loop_guard", "operator"]
    tokens_in: int = 0
    tokens_out: int = 0
    seen_calls: Counter[str] = field(default_factory=Counter)

    def trace(self) -> list[dict[str, Any]]:
        return [step.as_log() for step in self.steps]


def error_payload(error: ToolError) -> dict[str, Any]:
    """Единый вид ошибки для контекста модели."""
    return {"error": error.model_dump()}


def short(value: dict[str, Any], limit: int = 400) -> str:
    """Не кладём в журнал длинные результаты целиком."""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"
