"""Harness исполнения инструментов: валидация, подтверждение, повторы, сбои (перенос из ДЗ1).

`execute_tool` проверяет аргументы по схеме, спрашивает человека перед действием,
повторяет чтение при сбое (у действия повторов нет — нужен ключ идемпотентности) и
всегда возвращает результат или ошибку как данные, а не исключение. Теперь async:
реальные инструменты (A-2) ходят в домены и БД.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from core.app.agent.contracts import (
    ConfirmationCard,
    Tool,
    ToolCall,
    ToolContext,
    ToolError,
    error_payload,
)

_TOOL_BY_NAME: dict[str, Tool] = {}
"""Каталог текущего запуска: заполняет `register_tools` из `tools.py`.

В ДЗ1 каталог был константой модуля. Здесь реестр один на процесс: инструменты
продукта фиксированы (A-2), регистрация идемпотентна и вызывается сборкой графа.
"""

_READ_ATTEMPTS = 2
_RETRYABLE = {"timeout", "unavailable", "busy"}


def register_tools(tools: tuple[Tool, ...]) -> None:
    """Зарегистрировать каталог инструментов (идемпотентно, для `execute_tool`)."""
    _TOOL_BY_NAME.clear()
    _TOOL_BY_NAME.update({tool.name: tool for tool in tools})


def tool_by_name(name: str) -> Tool | None:
    return _TOOL_BY_NAME.get(name)


def registered_tools() -> tuple[Tool, ...]:
    return tuple(_TOOL_BY_NAME.values())


def _validation_error(exc: ValidationError) -> ToolError:
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first.get("loc", ())) or "аргументы"
    return ToolError(
        type="validation",
        message=f"{field}: {first.get('msg', 'неверное значение')}",
        hint="исправьте аргумент и вызовите инструмент снова; допустимые значения — в схеме",
    )


def _fault_error(tool: Tool, kind: str) -> ToolError:
    if kind == "timeout":
        return ToolError(
            type="timeout",
            message=f"{tool.name} не ответил за отведённое время",
            hint="не выдумывайте данные: повторите чтение позже или предложите оператора",
        )
    if kind == "unavailable":
        return ToolError(
            type="unavailable",
            message=f"{tool.name} временно недоступен",
            hint="попробуйте другой инструмент или честно скажите, что сервис недоступен",
        )
    return ToolError(type="busy", message=f"{tool.name} перегружен", hint="повторите позже")


async def execute_tool(
    call: ToolCall, ctx: ToolContext
) -> tuple[dict[str, Any], ToolError | None, str | None]:
    """Проверить, подтвердить, выполнить. Возвращает (результат, ошибка, кто подтвердил)."""
    tool = _TOOL_BY_NAME.get(call.name)
    if tool is None:
        error = ToolError(
            type="not_found",
            message=f"инструмента {call.name} нет",
            hint="доступны: " + ", ".join(sorted(_TOOL_BY_NAME)),
        )
        return error_payload(error), error, None

    raw = call.arguments
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            error = ToolError(
                type="validation",
                message="аргументы не разбираются как JSON",
                hint="передайте объект аргументов по схеме инструмента",
            )
            return error_payload(error), error, None

    try:
        parsed = tool.args_model.model_validate(raw)
    except ValidationError as exc:
        error = _validation_error(exc)
        return error_payload(error), error, None

    confirmed_by: str | None = None
    if tool.requires_confirmation:
        card = ConfirmationCard(action=tool.name, params=parsed.model_dump())
        if ctx.confirm is None:
            confirmed = False
        else:
            confirmed = ctx.confirm(card)
            if not isinstance(confirmed, bool):
                confirmed = bool(await confirmed)
        if not confirmed:
            return (
                {"cancelled": True, "reason": "человек не подтвердил действие"},
                None,
                None,
            )
        confirmed_by = str(ctx.account_id)

    # Сбои сервиса: у чтения пробуем ещё раз, у действия повторов нет (нужен ключ
    # идемпотентности и проверка статуса — слайд 32 лекции 2).
    attempts = _READ_ATTEMPTS if tool.kind == "read" else 1
    for attempt in range(1, attempts + 1):
        fault = ctx.take_fault(tool.name)
        if fault is None:
            result = await tool.fn(parsed, ctx)
            if isinstance(result, dict) and "error" in result:
                err = ToolError.model_validate(result["error"])
                return result, err, confirmed_by
            return result, None, confirmed_by
        if fault not in _RETRYABLE or attempt == attempts:
            error = _fault_error(tool, fault)
            if tool.kind == "action":
                error = ToolError(
                    type=error.type,
                    message=error.message,
                    hint="статус действия проверьте вручную: повтор без ключа идемпотентности "
                    "может выполнить его дважды",
                )
            return error_payload(error), error, confirmed_by
    # Недостижимо: цикл выше всегда возвращает результат или ошибку.
    raise RuntimeError("execute_tool: цикл повторов завершился без результата")


__all__ = ["execute_tool", "register_tools", "registered_tools", "tool_by_name"]
