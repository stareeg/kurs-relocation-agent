"""TB-4.4: уборка исходников батча — pending, keyboard, delete suppress, prefs plan."""

from __future__ import annotations


from unittest.mock import AsyncMock, patch


import pytest


from bot_app.services.batch_cleanup import (
    CB_BATCH_CLEANUP,
    CB_BATCH_CLEANUP_DONT_ASK,
    cleanup_ask_keyboard,
    delete_forward_messages,
    execute_pending_cleanup,
    plan_batch_cleanup,
    run_auto_cleanup,
    set_batch_cleanup_auto,
)

from bot_app.storage import batch_cleanup_pending

from core.domains.profile.telegram_prefs import TelegramPrefs


@pytest.fixture(autouse=True)
def _clear_pending() -> None:

    batch_cleanup_pending._PENDING.clear()  # noqa: SLF001

    yield

    batch_cleanup_pending._PENDING.clear()  # noqa: SLF001


def test_cleanup_ask_keyboard_labels() -> None:

    kb = cleanup_ask_keyboard(5)

    rows = kb.inline_keyboard

    assert rows[0][0].text == "Подчистить 5 пересланных"

    assert rows[0][0].callback_data == CB_BATCH_CLEANUP

    assert rows[1][0].text == "Больше не спрашивать"

    assert rows[1][0].callback_data == CB_BATCH_CLEANUP_DONT_ASK


def test_pending_save_peek_pop() -> None:

    batch_cleanup_pending.save(7, [10, 11, 12])

    assert batch_cleanup_pending.peek(7) == [10, 11, 12]

    assert batch_cleanup_pending.pop(7) == [10, 11, 12]

    assert batch_cleanup_pending.pop(7) is None

    assert batch_cleanup_pending.peek(7) is None


def test_pending_overwrite_and_clear() -> None:

    batch_cleanup_pending.save(1, [1, 2])

    batch_cleanup_pending.save(1, [9])

    assert batch_cleanup_pending.peek(1) == [9]

    batch_cleanup_pending.clear(1)

    assert batch_cleanup_pending.peek(1) is None


@pytest.mark.asyncio
async def test_delete_forward_messages_suppresses_errors() -> None:

    bot = AsyncMock()

    bot.delete_message = AsyncMock(side_effect=[True, RuntimeError("gone"), True])

    n = await delete_forward_messages(bot, 42, [1, 2, 3])

    assert n == 2

    assert bot.delete_message.await_count == 3


@pytest.mark.asyncio
async def test_execute_pending_cleanup_empty() -> None:

    bot = AsyncMock()

    assert await execute_pending_cleanup(bot, 99) == 0

    bot.delete_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_pending_cleanup_deletes() -> None:

    batch_cleanup_pending.save(5, [100, 101])

    bot = AsyncMock()

    bot.delete_message = AsyncMock(return_value=True)

    n = await execute_pending_cleanup(bot, 5)

    assert n == 2

    assert batch_cleanup_pending.peek(5) is None


@pytest.mark.asyncio
async def test_plan_ask_saves_pending_and_markup() -> None:

    plan = await plan_batch_cleanup(3, [1, 2, 3], mode="ask")

    assert plan.mode == "ask"

    assert plan.reply_markup is not None

    assert batch_cleanup_pending.peek(3) == [1, 2, 3]

    assert await run_auto_cleanup(AsyncMock(), plan, 3) == 0


@pytest.mark.asyncio
async def test_plan_auto_no_pending_then_run_deletes() -> None:

    bot = AsyncMock()

    bot.delete_message = AsyncMock(return_value=True)

    plan = await plan_batch_cleanup(8, [4, 5], mode="auto")

    assert plan.mode == "auto"

    assert plan.reply_markup is None

    assert batch_cleanup_pending.peek(8) is None

    n = await run_auto_cleanup(bot, plan, 8)

    assert n == 2


@pytest.mark.asyncio
async def test_plan_off_clears_and_noop() -> None:

    batch_cleanup_pending.save(2, [1])

    plan = await plan_batch_cleanup(2, [9, 10], mode="off")

    assert plan.mode == "off"

    assert plan.reply_markup is None

    assert batch_cleanup_pending.peek(2) is None

    bot = AsyncMock()

    assert await run_auto_cleanup(bot, plan, 2) == 0

    bot.delete_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_plan_defaults_to_auto_when_mode_omitted() -> None:
    """Селекты prefs убраны: без mode всегда auto, prefs.batch_cleanup игнорируется."""

    prefs = TelegramPrefs(batch_cleanup="ask")

    with patch(
        "bot_app.services.batch_cleanup.get_telegram_prefs",
        AsyncMock(return_value=prefs),
    ):
        plan = await plan_batch_cleanup(11, [7, 8])

    assert plan.mode == "auto"
    assert plan.reply_markup is None
    assert batch_cleanup_pending.peek(11) is None


@pytest.mark.asyncio
async def test_set_batch_cleanup_auto_writes_prefs() -> None:

    current = TelegramPrefs(batch_cleanup="ask", digest="smart")

    saved: list[TelegramPrefs] = []

    async def fake_get(**_k):

        return current

    async def fake_set(prefs, **_k):

        saved.append(prefs)

    with (
        patch("bot_app.services.batch_cleanup.get_telegram_prefs", fake_get),
        patch("bot_app.services.batch_cleanup.set_telegram_prefs", fake_set),
        patch(
            "bot_app.services.batch_cleanup.resolve_default_account_id",
            AsyncMock(return_value=1),
        ),
    ):
        await set_batch_cleanup_auto()

    assert len(saved) == 1

    assert saved[0].batch_cleanup == "auto"

    assert saved[0].digest == "smart"


@pytest.mark.asyncio
async def test_set_batch_cleanup_auto_prefers_current_account_id_over_owner() -> None:
    """M8 (plans/multitenancy_gaps_2026_08_06.md §3.13): «Больше не спрашивать» должно
    переключить prefs ВЫЗЫВАЮЩЕГО, не владельца — раньше падало прямо на
    `resolve_default_account_id()` (владелец) даже когда bot-middleware знало, кто нажал."""
    from core.config import reset_current_account_id, set_current_account_id

    current = TelegramPrefs(batch_cleanup="ask")
    seen_account_ids: list[int | None] = []

    async def fake_get(*, account_id: int | None):
        seen_account_ids.append(account_id)
        return current

    async def fake_set(prefs, **_k):
        return None

    resolve_owner = AsyncMock(return_value=1)
    token = set_current_account_id(7)
    try:
        with (
            patch("bot_app.services.batch_cleanup.get_telegram_prefs", fake_get),
            patch("bot_app.services.batch_cleanup.set_telegram_prefs", fake_set),
            patch("bot_app.services.batch_cleanup.resolve_default_account_id", resolve_owner),
        ):
            await set_batch_cleanup_auto()
    finally:
        reset_current_account_id(token)

    assert seen_account_ids == [7]
    resolve_owner.assert_not_awaited()
