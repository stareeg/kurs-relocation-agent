"""TB-4.2 / TB-4.3: vacancy forward → батчер; одиночный / batch с progress+сводкой."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot_app.handlers.forwarded import (
    VacancyForwardItem,
    _dispatch_vacancy_batch,
    _process_vacancy_forward_batch,
)
from core.domains.opportunities.jobs import SOURCE_TELEGRAM_CHANNEL
from core.domains.opportunities.persist import ScoredJob


def _item(msg_id: int, *, text: str = "x" * 60, header: str = "test") -> VacancyForwardItem:
    return VacancyForwardItem(
        message_id=msg_id,
        text=text,
        source=SOURCE_TELEGRAM_CHANNEL,
        origin=f"tg_origin_{msg_id}",
        vacancy_id_prefix="tg",
        fallback_company="",
        header=header,
    )


def _scored(rec: str, score: int, *, vacancy_id: str = "v1") -> ScoredJob:
    job = SimpleNamespace(
        vacancy_id=vacancy_id,
        company="Acme",
        title="PM",
    )
    score_obj = SimpleNamespace(overall_score=score, recommendation=rec)
    return ScoredJob.model_construct(job=job, score=score_obj)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatch_single_calls_item_processor() -> None:
    bot = AsyncMock()
    single = AsyncMock()
    batch = AsyncMock()
    with (
        patch("bot_app.handlers.forwarded._process_vacancy_forward_item", single),
        patch("bot_app.handlers.forwarded._process_vacancy_forward_batch", batch),
    ):
        await _dispatch_vacancy_batch([_item(1)], bot=bot, chat_id=42, account_id=1)
    single.assert_awaited_once()
    assert single.await_args.args[0].message_id == 1
    batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_multi_calls_batch_processor() -> None:
    bot = AsyncMock()
    single = AsyncMock()
    batch = AsyncMock()
    items = [_item(1), _item(2)]
    with (
        patch("bot_app.handlers.forwarded._process_vacancy_forward_item", single),
        patch("bot_app.handlers.forwarded._process_vacancy_forward_batch", batch),
    ):
        await _dispatch_vacancy_batch(items, bot=bot, chat_id=42, account_id=1)
    batch.assert_awaited_once()
    assert [i.message_id for i in batch.await_args.args[0]] == [1, 2]
    single.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_empty_is_noop() -> None:
    bot = AsyncMock()
    with (
        patch(
            "bot_app.handlers.forwarded._process_vacancy_forward_item",
            AsyncMock(),
        ) as single,
        patch(
            "bot_app.handlers.forwarded._process_vacancy_forward_batch",
            AsyncMock(),
        ) as batch,
    ):
        await _dispatch_vacancy_batch([], bot=bot, chat_id=1, account_id=1)
    single.assert_not_awaited()
    batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_progress_summary_cards_only_apply() -> None:
    """≥2: progress → сводка → карточки только apply+ → меню after_score."""
    bot = AsyncMock()
    progress = SimpleNamespace(message_id=99, edit_text=AsyncMock())
    items = [_item(1), _item(2), _item(3)]
    scores = [
        _scored("strong_apply", 90, vacancy_id="s1"),
        _scored("skip", 20, vacancy_id="s2"),
        _scored("apply", 75, vacancy_id="s3"),
    ]

    async def fake_score(item: VacancyForwardItem, *, account_id: int) -> ScoredJob | None:
        return scores[item.message_id - 1]

    send = AsyncMock(return_value=progress)
    card = AsyncMock()
    show_menu = AsyncMock()
    plan = AsyncMock(
        return_value=SimpleNamespace(mode="off", reply_markup=None, message_ids=[1, 2, 3])
    )

    with (
        patch("bot_app.handlers.forwarded.safe_send", send),
        patch("bot_app.handlers.forwarded._score_vacancy_forward_item", side_effect=fake_score),
        patch("bot_app.handlers.forwarded._send_scored_card", card),
        patch("bot_app.handlers.forwarded.plan_batch_cleanup", plan),
        patch("bot_app.handlers.forwarded.run_auto_cleanup", AsyncMock(return_value=0)),
        patch("bot_app.services.menu_manager.show_menu", show_menu),
        patch("bot_app.services.menu_manager.after_score", lambda *a, **k: ("after", a, k)),
    ):
        await _process_vacancy_forward_batch(items, bot=bot, chat_id=7, account_id=1)

    # progress + summary
    assert send.await_count >= 2
    assert "Читаю 3 постов" in send.await_args_list[0].args[2]
    summary_call = send.await_args_list[1]
    summary_text = summary_call.args[2]
    assert "3 вакансий: 1 сильных / 1 подать / 1 мимо" in summary_text
    plan.assert_awaited_once()

    bot.delete_message.assert_awaited_once_with(7, 99)

    # Карточки только strong_apply + apply (не skip)
    assert card.await_count == 2
    card_vids = [c.kwargs["job"].vacancy_id for c in card.await_args_list]
    assert card_vids == ["s1", "s3"]
    assert all(c.kwargs.get("refresh_menu") is False for c in card.await_args_list)
    # off → reply_to сохраняется
    assert [c.kwargs["reply_to_message_id"] for c in card.await_args_list] == [1, 3]

    show_menu.assert_awaited_once()
    menu_ctx = show_menu.await_args.args[2]
    assert menu_ctx[0] == "after"
    assert menu_ctx[2]["batch_stats"].strong == 1
    assert menu_ctx[2]["batch_stats"].apply == 1
    assert menu_ctx[2]["batch_stats"].skip == 1


@pytest.mark.asyncio
async def test_batch_ask_cleanup_attaches_keyboard() -> None:
    bot = AsyncMock()
    progress = SimpleNamespace(message_id=50, edit_text=AsyncMock())
    items = [_item(10), _item(11)]
    kb = object()

    send = AsyncMock(return_value=progress)
    plan = AsyncMock(
        return_value=SimpleNamespace(mode="ask", reply_markup=kb, message_ids=[10, 11])
    )
    run_auto = AsyncMock(return_value=0)

    with (
        patch("bot_app.handlers.forwarded.safe_send", send),
        patch(
            "bot_app.handlers.forwarded._score_vacancy_forward_item",
            AsyncMock(return_value=_scored("skip", 10)),
        ),
        patch("bot_app.handlers.forwarded._send_scored_card", AsyncMock()),
        patch("bot_app.handlers.forwarded.plan_batch_cleanup", plan),
        patch("bot_app.handlers.forwarded.run_auto_cleanup", run_auto),
        patch("bot_app.services.menu_manager.show_menu", AsyncMock()),
        patch("bot_app.services.menu_manager.after_score", lambda *a, **k: "ctx"),
    ):
        await _process_vacancy_forward_batch(items, bot=bot, chat_id=3, account_id=1)

    summary_kwargs = send.await_args_list[1].kwargs
    assert summary_kwargs.get("reply_markup") is kb
    run_auto.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_auto_cleanup_no_reply_to_on_cards() -> None:
    bot = AsyncMock()
    progress = SimpleNamespace(message_id=50, edit_text=AsyncMock())
    items = [_item(1), _item(2)]
    card = AsyncMock()
    run_auto = AsyncMock(return_value=2)

    with (
        patch("bot_app.handlers.forwarded.safe_send", AsyncMock(return_value=progress)),
        patch(
            "bot_app.handlers.forwarded._score_vacancy_forward_item",
            AsyncMock(return_value=_scored("apply", 80, vacancy_id="a1")),
        ),
        patch("bot_app.handlers.forwarded._send_scored_card", card),
        patch(
            "bot_app.handlers.forwarded.plan_batch_cleanup",
            AsyncMock(
                return_value=SimpleNamespace(mode="auto", reply_markup=None, message_ids=[1, 2])
            ),
        ),
        patch("bot_app.handlers.forwarded.run_auto_cleanup", run_auto),
        patch("bot_app.services.menu_manager.show_menu", AsyncMock()),
        patch("bot_app.services.menu_manager.after_score", lambda *a, **k: "ctx"),
    ):
        await _process_vacancy_forward_batch(items, bot=bot, chat_id=9, account_id=1)

    run_auto.assert_awaited_once()
    assert card.await_count == 2
    assert all(c.kwargs["reply_to_message_id"] is None for c in card.await_args_list)
