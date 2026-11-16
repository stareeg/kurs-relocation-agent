"""Harness инструментов (перенос из ДЗ1 в `core/app/agent`, A-2): валидация, права,
подтверждение, сбои, идемпотентность.

Инструменты здесь — фейковые async-функции на тех же контрактах: проверяется сам
`execute_tool`, а не домены. Реальные инструменты продукта — `test_agent_tools.py`.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import pytest
from pydantic import BaseModel, Field

from core.app.agent.contracts import ConfirmationCard, Tool, ToolCall, ToolContext, ToolError
from core.app.agent.toolkit import execute_tool, register_tools, registered_tools
from core.app.agent.tools import ensure_tools_registered


class EchoArgs(BaseModel):
    value: int = Field(ge=0, le=100)


class NoteArgs(BaseModel):
    note: str = Field(min_length=10, max_length=50)


async def echo(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    assert isinstance(args, EchoArgs)
    return {"echo": args.value, "account": ctx.account_id}


async def queue_it(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    assert isinstance(args, NoteArgs)
    if args.note in ctx.submissions:
        return {**ctx.submissions[args.note], "idempotent_replay": True}
    submission = {"queued": True, "note": args.note}
    ctx.submissions[args.note] = submission
    return submission


async def flaky(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
    _ = args, ctx
    return {"ok": True}


_TEST_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="echo",
        description="Возвращает аргумент обратно.",
        args_model=EchoArgs,
        kind="read",
        fn=echo,
    ),
    Tool(
        name="queue_it",
        description="Действие с подтверждением.",
        args_model=NoteArgs,
        kind="action",
        fn=queue_it,
        requires_confirmation=True,
    ),
    Tool(
        name="flaky",
        description="Чтение для проверок сбоев.",
        args_model=EchoArgs,
        kind="read",
        fn=flaky,
    ),
)


@pytest.fixture(autouse=True)
def _isolated_toolset() -> Any:
    """Тестовый каталог инструментов на время теста, после — продуктовый (как в проде)."""
    register_tools(_TEST_TOOLS)
    yield
    ensure_tools_registered()


def call(name: str, args: dict | str, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


async def test_read_returns_result_and_session_scoped_context() -> None:
    result, error, _ = await execute_tool(call("echo", {"value": 5}), ToolContext(account_id=7))
    assert error is None
    assert result == {"echo": 5, "account": 7}


async def test_out_of_range_argument_is_data_not_exception() -> None:
    result, error, _ = await execute_tool(call("echo", {"value": 999}), ToolContext())
    assert error is not None
    assert error.type == "validation"
    assert "value" in error.message
    assert result["error"]["hint"]


async def test_unknown_tool_is_reported_with_allowed_names() -> None:
    result, error, _ = await execute_tool(call("drop_database", {}), ToolContext())
    assert error is not None
    assert error.type == "not_found"
    assert "echo" in error.hint
    assert result["error"]["type"] == "not_found"


async def test_broken_json_arguments_are_returned_to_model() -> None:
    result, error, _ = await execute_tool(call("echo", "{value: 1"), ToolContext())
    assert error is not None
    assert error.type == "validation"
    assert "JSON" in error.message
    assert result["error"]["type"] == "validation"


async def test_action_is_not_executed_without_confirmation() -> None:
    context = ToolContext(confirm=lambda card: False)
    result, error, confirmed_by = await execute_tool(
        call("queue_it", {"note": "Подтверждаю отправку отклика"}), context
    )
    assert error is None
    assert confirmed_by is None
    assert result["cancelled"] is True
    assert context.submissions == {}


async def test_action_without_confirm_hook_is_cancelled() -> None:
    """Нет хука подтверждения — действие не выполняется (A-2: решение за человеком)."""
    result, error, _ = await execute_tool(
        call("queue_it", {"note": "Подтверждаю отправку отклика"}), ToolContext()
    )
    assert error is None
    assert result["cancelled"] is True


async def test_action_runs_after_async_confirmation_and_is_idempotent() -> None:
    cards: list[ConfirmationCard] = []

    async def confirm(card: ConfirmationCard) -> bool:
        cards.append(card)
        return True

    context = ToolContext(confirm=confirm)
    payload = call("queue_it", {"note": "Подтверждаю отправку отклика"})

    first, error, confirmed_by = await execute_tool(payload, context)
    second, error2, _ = await execute_tool(payload, context)

    assert error is None and error2 is None
    assert confirmed_by == str(context.account_id)
    assert first["queued"] is True
    assert second["idempotent_replay"] is True
    assert second["note"] == first["note"]
    # Человек подтверждает конкретные параметры, а не фразу модели.
    assert cards[0].params["note"] == "Подтверждаю отправку отклика"


async def test_read_retries_twice_then_returns_timeout_as_data() -> None:
    context = ToolContext(faults={"flaky": deque(["timeout", "timeout"])})
    result, error, _ = await execute_tool(call("flaky", {"value": 1}), context)
    assert error is not None
    assert error.type == "timeout"
    assert result["error"]["hint"]
    assert context.faults["flaky"] == deque()


async def test_read_recovers_after_single_fault() -> None:
    context = ToolContext(faults={"flaky": deque(["timeout"])})
    result, error, _ = await execute_tool(call("flaky", {"value": 1}), context)
    assert error is None
    assert result["ok"] is True


async def test_action_has_no_automatic_retry() -> None:
    context = ToolContext(
        confirm=lambda card: True, faults={"queue_it": deque(["timeout"])}
    )
    result, error, _ = await execute_tool(
        call("queue_it", {"note": "Подтверждаю отправку отклика"}), context
    )
    assert error is not None
    assert error.type == "timeout"
    assert "идемпотентности" in error.hint
    assert result["error"]["type"] == "timeout"


async def test_tool_error_from_function_body_is_data() -> None:
    """Инструмент вернул `error` в результате — это доменная ошибка, не сбой harness."""

    async def boom(args: BaseModel, ctx: ToolContext) -> dict[str, Any]:
        _ = args, ctx
        return {"error": ToolError(type="not_found", message="пусто", hint="поищите").model_dump()}

    register_tools(
        (
            Tool(
                name="boom",
                description="Отдаёт готовую ошибку.",
                args_model=EchoArgs,
                kind="read",
                fn=boom,
            ),
        )
    )
    result, error, _ = await execute_tool(call("boom", {"value": 1}), ToolContext())
    assert error is not None
    assert error.type == "not_found"
    assert result["error"]["message"] == "пусто"


def test_registered_tools_returns_catalog() -> None:
    assert {tool.name for tool in registered_tools()} == {"echo", "queue_it", "flaky"}
