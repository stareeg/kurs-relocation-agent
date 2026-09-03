"""Онбординг в боте: куда вставлять токен, без путаницы с «другим Telegram»."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot_app.handlers import menu as menu_handlers


@pytest.mark.asyncio
async def test_send_token_next_steps_points_to_site_not_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """После голого токена — отдельное сообщение: сайт + «Аккаунт», не «ответь боту»."""
    monkeypatch.setattr(
        menu_handlers,
        "get_bot_settings",
        lambda: SimpleNamespace(web_url="https://copilot.example.com/"),
    )
    send = AsyncMock()
    monkeypatch.setattr(menu_handlers, "safe_send", send)

    await menu_handlers._send_token_next_steps(AsyncMock(), chat_id=42)

    send.assert_awaited_once()
    body = send.await_args.args[2]
    assert "не обратно в этот чат" in body
    assert "Аккаунт" in body
    assert body.endswith("https://copilot.example.com")
    assert "Добавить аккаунт" not in body


def test_add_account_copy_is_secondary_not_onboarding() -> None:
    """Промпт второго Telegram явно говорит «только если уже есть» + куда токен новичку."""
    assert "только если" in menu_handlers._ADD_ACCOUNT_PROMPT.lower()
    assert "Аккаунт" in menu_handlers._ADD_ACCOUNT_PROMPT
    assert "на сайте" in menu_handlers._ADD_ACCOUNT_ALREADY_LINKED.lower()
    assert "Токен авторизации" in menu_handlers._ADD_ACCOUNT_NEED_TOKEN_FIRST
