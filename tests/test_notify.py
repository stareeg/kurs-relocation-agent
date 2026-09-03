"""M8 (plans/multitenancy_gaps_2026_08_06.md §5.5/§3.13): `notify_account` доставляет в
primary чат аккаунта, `broadcast_to_active_accounts` — цикл поверх него."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from bot_app.services.notify import broadcast_to_active_accounts, notify_account
from core.platform.repo.accounts import AccountRecord


def _account(
    account_id: int,
    *,
    chat_id: int | None,
    status: str = "active",
) -> AccountRecord:
    return AccountRecord(
        id=account_id,
        telegram_user_id=1000 + account_id,
        telegram_username=None,
        telegram_chat_id=chat_id,
        role="owner" if account_id == 1 else "member",
        status=status,
    )


@pytest.mark.asyncio
async def test_notify_account_sends_to_primary_chat() -> None:
    account = _account(1, chat_id=555)
    bot = AsyncMock()

    with (
        patch("bot_app.services.notify.get_account_by_id", AsyncMock(return_value=account)),
        patch("bot_app.services.notify.safe_send", AsyncMock(return_value="sent")) as fake_send,
    ):
        result = await notify_account(bot, 1, "привет")

    assert result == "sent"
    fake_send.assert_awaited_once()
    assert fake_send.await_args.args[:2] == (bot, 555)


@pytest.mark.asyncio
async def test_notify_account_skips_without_chat_id() -> None:
    account = _account(2, chat_id=None)

    with (
        patch("bot_app.services.notify.get_account_by_id", AsyncMock(return_value=account)),
        patch("bot_app.services.notify.safe_send", AsyncMock()) as fake_send,
    ):
        result = await notify_account(AsyncMock(), 2, "привет")

    assert result is None
    fake_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_account_skips_disabled_account() -> None:
    account = _account(3, chat_id=555, status="disabled")

    with (
        patch("bot_app.services.notify.get_account_by_id", AsyncMock(return_value=account)),
        patch("bot_app.services.notify.safe_send", AsyncMock()) as fake_send,
    ):
        result = await notify_account(AsyncMock(), 3, "привет")

    assert result is None
    fake_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_notify_account_skips_unknown_account() -> None:
    with (
        patch("bot_app.services.notify.get_account_by_id", AsyncMock(return_value=None)),
        patch("bot_app.services.notify.safe_send", AsyncMock()) as fake_send,
    ):
        result = await notify_account(AsyncMock(), 99, "привет")

    assert result is None
    fake_send.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_skips_accounts_without_message_and_counts_delivered() -> None:
    owner = _account(1, chat_id=100)
    member_no_chat = _account(2, chat_id=None)
    member = _account(3, chat_id=300)

    async def build_message(account: AccountRecord) -> str | None:
        if account.id == member_no_chat.id:
            return "no chat but has text"
        if account.id == owner.id:
            return None  # нечего слать владельцу в этом сценарии
        return f"привет {account.id}"

    async def fake_notify(bot: object, account_id: int, text: str) -> object | None:
        _ = bot, text
        return "sent" if account_id == member.id else None

    with (
        patch(
            "bot_app.services.notify.list_active_accounts",
            AsyncMock(return_value=[owner, member_no_chat, member]),
        ),
        patch("bot_app.services.notify.notify_account", AsyncMock(side_effect=fake_notify)),
    ):
        stats = await broadcast_to_active_accounts(AsyncMock(), build_message)

    assert stats == {"total": 3, "sent": 1, "skipped": 2}
