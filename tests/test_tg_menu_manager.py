"""TB-3.8: menu_manager + реестр — снапшоты кнопок, refresh, best-effort PG."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from bot_app.services import menu_manager as mm
from bot_app.storage import message_registry as reg
from bot_app.storage.message_registry import TrackedMessage

_WEB = "https://app.example"
_HTTP_LOCAL = "http://localhost:5173"


def _kb_snapshot(markup: Any) -> list[list[tuple[str, str]]]:
    """Ряды кнопок → [(text, callback_data|url), ...]."""
    rows: list[list[tuple[str, str]]] = []
    for row in markup.inline_keyboard:
        cells: list[tuple[str, str]] = []
        for btn in row:
            target = btn.callback_data or btn.url or ""
            cells.append((btn.text, target))
        rows.append(cells)
    return rows


def test_build_menu_idle_snapshot() -> None:
    # Токен — главный ряд; «Привязать другой Telegram» — вторичный (не peer CTA онбординга).
    # «Веб» вынесен в закреп; «Ключ OpenRouter» — только в вебе («Аккаунт» / админ-панель).
    expected = [
        [("Токен авторизации", mm.CB_AUTH_TOKEN)],
        [("Привязать другой Telegram", mm.CB_ADD_ACCOUNT)],
    ]
    assert _kb_snapshot(mm.build_menu(mm.idle(), web_url=_WEB)) == expected
    # http/localhost — те же callback-кнопки (URL-кнопок в меню больше нет).
    assert _kb_snapshot(mm.build_menu(mm.idle(), web_url=_HTTP_LOCAL)) == expected


def test_build_menu_member_home_matches_idle() -> None:
    # member_home — тот же минимальный набор, что idle (токен + второй Telegram).
    assert _kb_snapshot(mm.build_menu(mm.member_home(), web_url=_WEB)) == _kb_snapshot(
        mm.build_menu(mm.idle(), web_url=_WEB)
    )


def test_auth_token_kb_first_contact_only_token() -> None:
    # Первый /start: только выдача токена — без «Привязать другой Telegram».
    assert _kb_snapshot(mm.auth_token_kb()) == [
        [("Токен авторизации", mm.CB_AUTH_TOKEN)],
    ]


def test_build_menu_after_score_snapshot() -> None:
    assert _kb_snapshot(mm.build_menu(mm.after_score("vac-1"), web_url=_WEB)) == [
        [("Топ за сегодня", mm.CB_TOP_TODAY), ("Подчистить чат", mm.CB_CLEANUP_CHAT)],
    ]


def test_build_menu_after_hr_snapshot() -> None:
    assert _kb_snapshot(mm.build_menu(mm.after_hr("vac-hr"), web_url=_WEB)) == [
        [
            ("Открыть тред", f"{_WEB}/chat?vacancy=vac-hr"),
            ("HR-контакты", mm.CB_HR_CONTACTS),
        ],
    ]
    # Без https — только callback, без deeplink.
    assert _kb_snapshot(mm.build_menu(mm.after_hr("vac-hr"), web_url=_HTTP_LOCAL)) == [
        [("HR-контакты", mm.CB_HR_CONTACTS)],
    ]
    assert _kb_snapshot(mm.build_menu(mm.after_hr(""), web_url=_WEB)) == [
        [("HR-контакты", mm.CB_HR_CONTACTS)],
    ]


def test_build_menu_labels_have_no_decorative_emoji() -> None:
    contexts = [
        mm.idle(),
        mm.after_score("v"),
        mm.after_hr("v"),
        mm.member_home(),
    ]
    for ctx in contexts:
        for row in mm.build_menu(ctx, web_url=_WEB).inline_keyboard:
            for btn in row:
                assert not any(ch in btn.text for ch in "🔍💰🟢🔴📋⚡✏➕🗑▶⬅🌐✅⛔"), (
                    f"emoji in label {btn.text!r} for {ctx.kind}"
                )


def test_menu_text_by_context() -> None:
    assert mm.menu_text(mm.idle()) == "Меню"
    assert mm.menu_text(mm.member_home()) == "Меню"
    assert mm.menu_text(mm.after_hr("x")) == "HR разобран"
    assert mm.menu_text(mm.after_score("v")) == "Меню"
    assert (
        mm.menu_text(
            mm.after_score(
                "v",
                batch_stats=mm.BatchStats(total=5, strong=1, apply=2, skip=2),
            )
        )
        == "Оценено 5: сильных 1, подать 2, мимо 2"
    )


@pytest.mark.asyncio
async def test_refresh_edits_existing_menu_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    """Есть отслеженное меню → edit-in-place, ничего не удаляем и не шлём заново."""
    previous = [
        TrackedMessage(
            id=1,
            chat_id=42,
            message_id=100,
            kind="menu",
            vacancy_id=None,
            cleanup_after=None,
        ),
    ]
    pop = AsyncMock(return_value=previous)
    track = AsyncMock(return_value=1)
    send = AsyncMock()
    monkeypatch.setattr(mm, "pop_kind", pop)
    monkeypatch.setattr(mm, "track", track)
    monkeypatch.setattr(mm, "safe_send", send)

    bot = AsyncMock()
    edited = SimpleNamespace(message_id=100)
    # refresh использует isinstance-проверку Message — подменяем на фейковый тип.
    monkeypatch.setattr(mm, "Message", SimpleNamespace)  # isinstance(edited, Message) → True
    bot.edit_message_text = AsyncMock(return_value=edited)
    result = await mm.refresh(bot, 42, mm.idle(), web_url=_WEB)

    assert result is edited
    pop.assert_awaited_once_with(42, reg.KIND_MENU)
    bot.edit_message_text.assert_awaited_once()
    ekwargs = bot.edit_message_text.await_args.kwargs
    assert ekwargs["chat_id"] == 42
    assert ekwargs["message_id"] == 100
    send.assert_not_awaited()
    bot.delete_message.assert_not_awaited()
    track.assert_awaited_once_with(42, 100, reg.KIND_MENU)


@pytest.mark.asyncio
async def test_refresh_deletes_extras_and_edits_newest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Несколько меню в реестре → лишние удаляем, новейшее редактируем."""
    previous = [
        TrackedMessage(
            id=1, chat_id=42, message_id=100, kind="menu", vacancy_id=None, cleanup_after=None
        ),
        TrackedMessage(
            id=2, chat_id=42, message_id=101, kind="menu", vacancy_id=None, cleanup_after=None
        ),
    ]
    monkeypatch.setattr(mm, "pop_kind", AsyncMock(return_value=previous))
    monkeypatch.setattr(mm, "track", AsyncMock())
    monkeypatch.setattr(mm, "safe_send", AsyncMock())

    bot = AsyncMock()
    edited = SimpleNamespace(message_id=101)
    monkeypatch.setattr(mm, "Message", SimpleNamespace)
    bot.edit_message_text = AsyncMock(return_value=edited)
    await mm.refresh(bot, 42, mm.idle(), web_url=_WEB)

    # Старое (message_id=100) удалено, новейшее (101) отредактировано.
    bot.delete_message.assert_awaited_once_with(42, 100)
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 101


@pytest.mark.asyncio
async def test_refresh_falls_back_to_delete_and_send_when_edit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edit не вышел (старое/удалено) → удалить старое и прислать новое."""
    previous = [
        TrackedMessage(
            id=1, chat_id=7, message_id=9, kind="menu", vacancy_id=None, cleanup_after=None
        ),
    ]
    monkeypatch.setattr(mm, "pop_kind", AsyncMock(return_value=previous))
    sent = SimpleNamespace(message_id=55)
    send = AsyncMock(return_value=sent)
    monkeypatch.setattr(mm, "safe_send", send)

    bot = AsyncMock()
    bot.edit_message_text = AsyncMock(side_effect=RuntimeError("message not found"))
    result = await mm.refresh(bot, 7, mm.idle(), web_url=_WEB)

    assert result is sent
    bot.delete_message.assert_awaited_once_with(7, 9)
    send.assert_awaited_once()
    kwargs = send.await_args.kwargs
    assert kwargs["track_kind"] == reg.KIND_MENU
    assert kwargs["parse_mode"] == "HTML"
    assert send.await_args.args[1] == 7
    assert send.await_args.args[2] == "Меню"


@pytest.mark.asyncio
async def test_show_menu_none_bot_is_noop() -> None:
    assert await mm.show_menu(None, 1, mm.idle()) is None


@pytest.mark.asyncio
async def test_registry_best_effort_when_pg_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("pg down")

    monkeypatch.setattr(reg, "get_pool", boom)
    assert await reg.track(1, 2, "menu") is None
    assert await reg.pop_kind(1, "menu") == []
    assert await reg.pop_by_vacancy(1, "card", "v1") == []
    assert await reg.due_cleanup() == []
