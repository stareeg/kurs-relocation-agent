"""Лента поддержки в карточке человека."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import core.platform.admin.service as admin_svc
from core.platform.admin.models import AdminError, AdminSupportMessage, AdminSupportThread
from core.platform.admin.service import send_support_message
from core.platform.repo.accounts import AccountRecord


def _account(**over: object) -> AccountRecord:
    base: dict[str, object] = dict(
        id=2,
        telegram_user_id=20,
        telegram_username="friend",
        telegram_chat_id=11,
        role="member",
        status="active",
    )
    base.update(over)
    return AccountRecord(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_send_support_user_enqueues_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_svc, "get_account_by_id", AsyncMock(return_value=_account()))
    enqueue = AsyncMock()
    monkeypatch.setattr(admin_svc, "enqueue_admin_telegram", enqueue)
    inserted = AdminSupportMessage(
        id=1, channel="user", role="admin", body="привет", reply_to_id=None
    )
    monkeypatch.setattr(admin_svc, "_insert_support_message", AsyncMock(return_value=inserted))
    monkeypatch.setattr(
        admin_svc,
        "load_support_thread",
        AsyncMock(return_value=AdminSupportThread(items=[inserted])),
    )
    thread = await send_support_message(2, channel="user", text="привет", actor_id=1)
    enqueue.assert_awaited_once()
    assert enqueue.await_args.kwargs["persist"] is False
    assert thread.items[0].body == "привет"


@pytest.mark.asyncio
async def test_send_support_rejects_empty() -> None:
    with pytest.raises(AdminError, match="Пустое"):
        await send_support_message(2, channel="user", text="  ", actor_id=1)
