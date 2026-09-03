"""/pause_autoapply (Фаза 7.4): резолвит аккаунт вызывающего, гасит все площадки, отвечает."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot_app.handlers import auto_apply as handler


def _message(user_id: int | None) -> SimpleNamespace:
    from_user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(from_user=from_user, answer=AsyncMock())


async def test_pause_command_stops_all_platforms_for_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(id=42)
    resolve_mock = AsyncMock(return_value=account)
    pause_mock = AsyncMock()
    monkeypatch.setattr(handler, "resolve_account", resolve_mock)
    monkeypatch.setattr(handler, "pause_all", pause_mock)

    message = _message(user_id=123)
    await handler.cmd_pause_autoapply(message)

    resolve_mock.assert_awaited_once_with(user_id=123)
    pause_mock.assert_awaited_once_with(account_id=42)
    message.answer.assert_awaited_once()


async def test_pause_command_no_account_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    resolve_mock = AsyncMock(return_value=None)
    pause_mock = AsyncMock()
    monkeypatch.setattr(handler, "resolve_account", resolve_mock)
    monkeypatch.setattr(handler, "pause_all", pause_mock)

    message = _message(user_id=123)
    await handler.cmd_pause_autoapply(message)

    pause_mock.assert_not_called()
    message.answer.assert_not_called()


async def test_pause_command_no_from_user_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    pause_mock = AsyncMock()
    monkeypatch.setattr(handler, "pause_all", pause_mock)

    message = _message(user_id=None)
    await handler.cmd_pause_autoapply(message)

    pause_mock.assert_not_called()
    message.answer.assert_not_called()
