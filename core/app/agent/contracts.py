"""Контракты инструментов агента курса (перенос из ДЗ1, A-2).

Восемь полей контракта (требование семинара): имя, описание, аргументы, что не от модели,
результат, ошибки, тип (чтение/действие), отказ. Здесь они разложены по классам: `Tool`
описывает первые три и последние три, `ToolContext` — то, что код знает сам, `ToolError` —
формат ошибки.

Отличия от ДЗ1: `Tool.fn` — async (реальные инструменты ходят в домены и БД), а
`ToolContext` вместо демо-строк несёт `account_id` запроса и опциональный `db`
(Executor пула) — в проде `None`, домены сами открывают пул; в тестах подставляется
двойник. Гражданство останется в контексте для инструмента правил страны (K-1).
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from core.platform.db.pool import Executor


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
    """То, что код знает сам и модель выбирать не должна: аккаунт, БД, сбои, подтверждения."""

    account_id: int = 1
    db: Executor | None = None  # прод: None (домены сами открывают пул), тесты: двойник
    citizenship: str = "RU"  # для инструмента правил страны (K-1); берётся из профиля, не у модели
    faults: dict[str, deque[str]] = field(default_factory=dict)
    confirm: Callable[[ConfirmationCard], Awaitable[bool] | bool] | None = None
    submissions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def take_fault(self, tool: str) -> str | None:
        """Запланированный сбой для тестов: «инструмент вернул ошибку» без сети."""
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
    fn: Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]]
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


def error_payload(error: ToolError) -> dict[str, Any]:
    """Единый вид ошибки для контекста модели."""
    return {"error": error.model_dump()}


def short(value: dict[str, Any], limit: int = 400) -> str:
    """Не кладём в журнал длинные результаты целиком."""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


__all__ = [
    "ConfirmationCard",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolError",
    "error_payload",
    "short",
]
