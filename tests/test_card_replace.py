"""TB-4.5: повторная карточка не плодится; progress/service TTL 1ч."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bot_app.services.card_replace import can_edit_card, send_or_replace_card
from bot_app.storage import message_registry as reg
from bot_app.storage.message_registry import TrackedMessage
from core.domains.profile.telegram_prefs import TelegramPrefs


@pytest.fixture(autouse=True)
def _fake_default_account_id():
    """`_resolve_card_style` резолвит account_id перед get_telegram_prefs (Этап 2) — без
    живого Postgres `resolve_default_account_id()` упал бы и тихо увёл стиль карточки на
    text (except Exception внутри `_resolve_card_style`), пряча настоящую причину падения
    тестов, ожидающих card_style="image"."""
    with patch(
        "bot_app.services.card_replace.resolve_default_account_id", AsyncMock(return_value=1)
    ):
        yield


def _tracked(
    message_id: int = 10,
    *,
    created_at: datetime | None = None,
    vacancy_id: str = "v1",
) -> TrackedMessage:
    return TrackedMessage(
        id=1,
        chat_id=42,
        message_id=message_id,
        kind="card",
        vacancy_id=vacancy_id,
        cleanup_after=None,
        created_at=created_at,
    )


def test_can_edit_card_text_within_48h() -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    prev = _tracked(created_at=now - timedelta(hours=47))
    assert can_edit_card(prev, card_style="text", now=now)


def test_can_edit_card_rejects_old_image_or_missing_ts() -> None:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
    old = _tracked(created_at=now - timedelta(hours=49))
    assert not can_edit_card(old, card_style="text", now=now)
    fresh = _tracked(created_at=now - timedelta(hours=1))
    assert not can_edit_card(fresh, card_style="image", now=now)
    assert not can_edit_card(_tracked(created_at=None), card_style="text", now=now)


@pytest.mark.asyncio
async def test_send_or_replace_edits_when_eligible() -> None:
    now = datetime.now(UTC)
    prev = _tracked(55, created_at=now - timedelta(hours=1))
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=SimpleNamespace(message_id=55))
    track = AsyncMock(return_value=1)
    send = AsyncMock()

    with (
        patch(
            "bot_app.services.card_replace.pop_by_vacancy",
            AsyncMock(return_value=[prev]),
        ),
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="text")),
        ),
        patch("bot_app.services.card_replace.track", track),
        patch("bot_app.services.card_replace.safe_send", send),
    ):
        result = await send_or_replace_card(
            bot,
            42,
            vacancy_id="v1",
            text="card body",
            reply_markup="kb",
            reply_to_message_id=99,
        )

    # SimpleNamespace не Message — возвращаем None, но edit+track уже прошли.
    assert result is None
    bot.edit_message_text.assert_awaited_once()
    track.assert_awaited_once_with(42, 55, reg.KIND_CARD, vacancy_id="v1")
    send.assert_not_awaited()
    bot.delete_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_or_replace_deletes_then_sends_for_image_style() -> None:
    now = datetime.now(UTC)
    prev = _tracked(70, created_at=now - timedelta(hours=1))
    bot = AsyncMock()
    bot.delete_message = AsyncMock()
    sent = SimpleNamespace(message_id=100)
    send = AsyncMock(return_value=sent)

    with (
        patch(
            "bot_app.services.card_replace.pop_by_vacancy",
            AsyncMock(return_value=[prev]),
        ),
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="image")),
        ),
        patch("bot_app.services.card_replace.safe_send", send),
    ):
        result = await send_or_replace_card(
            bot,
            42,
            vacancy_id="v1",
            text="card body",
            reply_to_message_id=9,
        )

    assert result is sent
    bot.delete_message.assert_awaited_once_with(42, 70)
    bot.edit_message_text.assert_not_awaited()
    assert send.await_args.kwargs["track_kind"] == reg.KIND_CARD
    assert send.await_args.kwargs["vacancy_id"] == "v1"
    assert send.await_args.kwargs["reply_to_message_id"] == 9


@pytest.mark.asyncio
async def test_send_or_replace_deletes_extras_keeps_edit_primary() -> None:
    now = datetime.now(UTC)
    newer = _tracked(2, created_at=now - timedelta(minutes=5))
    older = _tracked(1, created_at=now - timedelta(hours=2))
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value=SimpleNamespace(message_id=2))
    bot.delete_message = AsyncMock()

    with (
        patch(
            "bot_app.services.card_replace.pop_by_vacancy",
            AsyncMock(return_value=[newer, older]),
        ),
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="text")),
        ),
        patch("bot_app.services.card_replace.track", AsyncMock()),
        patch("bot_app.services.card_replace.safe_send", AsyncMock()),
    ):
        await send_or_replace_card(bot, 42, vacancy_id="v1", text="x")

    bot.delete_message.assert_awaited_once_with(42, 1)
    assert bot.edit_message_text.await_args.kwargs["message_id"] == 2


@pytest.mark.asyncio
async def test_send_or_replace_falls_back_when_edit_fails() -> None:
    now = datetime.now(UTC)
    prev = _tracked(8, created_at=now - timedelta(hours=1))
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock(side_effect=RuntimeError("can't edit"))
    bot.delete_message = AsyncMock()
    send = AsyncMock(return_value=SimpleNamespace(message_id=99))

    with (
        patch(
            "bot_app.services.card_replace.pop_by_vacancy",
            AsyncMock(return_value=[prev]),
        ),
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="text")),
        ),
        patch("bot_app.services.card_replace.safe_send", send),
    ):
        result = await send_or_replace_card(bot, 42, vacancy_id="v1", text="x")

    assert result is not None
    bot.delete_message.assert_awaited_once_with(42, 8)
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_or_replace_with_photo_uses_safe_send_photo() -> None:
    now = datetime.now(UTC)
    prev = _tracked(70, created_at=now - timedelta(hours=1))
    bot = AsyncMock()
    bot.delete_message = AsyncMock()
    sent = SimpleNamespace(message_id=100)
    send_photo = AsyncMock(return_value=sent)
    send = AsyncMock()

    with (
        patch(
            "bot_app.services.card_replace.pop_by_vacancy",
            AsyncMock(return_value=[prev]),
        ),
        patch("bot_app.services.card_replace.safe_send_photo", send_photo),
        patch("bot_app.services.card_replace.safe_send", send),
    ):
        result = await send_or_replace_card(
            bot,
            42,
            vacancy_id="v1",
            text="Acme — PM · 88/100 · Сильный фит",
            photo=b"\x89PNG fake",
            reply_to_message_id=9,
            parse_mode=None,
            reply_markup="kb",
        )

    assert result is sent
    bot.delete_message.assert_awaited_once_with(42, 70)
    send.assert_not_awaited()
    assert send_photo.await_args.kwargs["caption"] == "Acme — PM · 88/100 · Сильный фит"
    assert send_photo.await_args.args[2] == b"\x89PNG fake"
    assert send_photo.await_args.kwargs["track_kind"] == reg.KIND_CARD
    assert send_photo.await_args.kwargs["vacancy_id"] == "v1"


@pytest.mark.asyncio
async def test_send_score_card_image_style_sends_photo() -> None:
    from bot_app.services.card_replace import send_or_replace_score_card
    from core.domains.opportunities.jobs import Job
    from core.domains.opportunities.models import (
        BurnoutRisk,
        GradeMatch,
        RemoteAbroadCompat,
        RoleContentMatch,
        SalaryInfo,
        ScoreResult,
    )

    job = Job(
        vacancy_text="x",
        company="Acme",
        title="PM",
        vacancy_id="v1",
        source="hh",
    )
    score = ScoreResult(
        overall_score=88,
        recommendation="strong_apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="x", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="v",
    )
    bot = AsyncMock()
    replace = AsyncMock(return_value=SimpleNamespace(message_id=1))

    with (
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="image")),
        ),
        patch(
            "bot_app.services.card_image.render_score_card",
            return_value=b"\x89PNG\r\n\x1a\nxx",
        ) as render,
        patch("bot_app.services.card_replace.send_or_replace_card", replace),
    ):
        await send_or_replace_score_card(
            bot, 42, job=job, score=score, header="Тест", reply_to_message_id=7
        )

    render.assert_called_once()
    kwargs = replace.await_args.kwargs
    assert kwargs["photo"] == b"\x89PNG\r\n\x1a\nxx"
    assert kwargs["text"] == "Acme — PM · 88/100 · Сильный фит"
    assert kwargs["parse_mode"] is None
    assert kwargs["vacancy_id"] == "v1"
    assert kwargs["reply_to_message_id"] == 7


@pytest.mark.asyncio
async def test_send_score_card_render_failure_falls_back_to_text() -> None:
    from bot_app.services.card_replace import send_or_replace_score_card
    from core.domains.opportunities.jobs import Job
    from core.domains.opportunities.models import (
        BurnoutRisk,
        GradeMatch,
        RemoteAbroadCompat,
        RoleContentMatch,
        SalaryInfo,
        ScoreResult,
    )

    job = Job(vacancy_text="x", company="Acme", title="PM", vacancy_id="v1")
    score = ScoreResult(
        overall_score=70,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="x", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="v",
    )
    bot = AsyncMock()
    replace = AsyncMock(return_value=SimpleNamespace(message_id=1))

    with (
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="image")),
        ),
        patch(
            "bot_app.services.card_image.render_score_card",
            side_effect=RuntimeError("pillow boom"),
        ),
        patch("bot_app.services.card_replace.send_or_replace_card", replace),
    ):
        await send_or_replace_score_card(bot, 42, job=job, score=score, header="Заголовок")

    kwargs = replace.await_args.kwargs
    assert kwargs.get("photo") is None
    assert kwargs["parse_mode"] == "HTML"
    assert "88/100" not in kwargs["text"]  # full text card, not caption
    assert "Acme" in kwargs["text"]
    assert "70/100" in kwargs["text"]


@pytest.mark.asyncio
async def test_send_score_card_text_style_skips_render() -> None:
    from bot_app.services.card_replace import send_or_replace_score_card
    from core.domains.opportunities.jobs import Job
    from core.domains.opportunities.models import (
        BurnoutRisk,
        GradeMatch,
        RemoteAbroadCompat,
        RoleContentMatch,
        SalaryInfo,
        ScoreResult,
    )

    job = Job(vacancy_text="x", company="Co", title="Dev", vacancy_id="v2")
    score = ScoreResult(
        overall_score=55,
        recommendation="maybe",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=False, value_or_range="", note=""),
        role_content_match=RoleContentMatch(score=40, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="medium", reasoning="r"),
        company_type="unknown",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="?",
    )
    bot = AsyncMock()
    replace = AsyncMock()
    render = AsyncMock()

    with (
        patch(
            "bot_app.services.card_replace.get_telegram_prefs",
            AsyncMock(return_value=TelegramPrefs(card_style="text")),
        ),
        patch("bot_app.services.card_image.render_score_card", render),
        patch("bot_app.services.card_replace.send_or_replace_card", replace),
    ):
        await send_or_replace_score_card(bot, 1, job=job, score=score, header="h")

    render.assert_not_called()
    assert replace.await_args.kwargs.get("photo") is None
    assert replace.await_args.kwargs["parse_mode"] == "HTML"


@pytest.mark.asyncio
async def test_send_without_vacancy_id_skips_pop() -> None:
    bot = AsyncMock()
    send = AsyncMock(return_value=SimpleNamespace(message_id=1))
    pop = AsyncMock()
    with (
        patch("bot_app.services.card_replace.pop_by_vacancy", pop),
        patch("bot_app.services.card_replace.safe_send", send),
    ):
        await send_or_replace_card(bot, 1, vacancy_id="", text="x")
    pop.assert_not_awaited()
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_card_style_prefers_current_account_id_over_owner() -> None:
    """M8 (plans/multitenancy_gaps_2026_08_06.md §3.13): вызывающий member должен получить
    СВОЙ card_style — раньше `_resolve_card_style` всегда падало на владельца
    (`resolve_default_account_id`), даже когда bot-middleware уже знало вызывающего."""
    from core.config import reset_current_account_id, set_current_account_id

    seen_account_ids: list[int | None] = []

    async def fake_prefs(*, account_id: int | None) -> TelegramPrefs:
        seen_account_ids.append(account_id)
        return TelegramPrefs(card_style="text")

    bot = AsyncMock()
    token = set_current_account_id(7)
    try:
        with (
            patch("bot_app.services.card_replace.pop_by_vacancy", AsyncMock(return_value=[])),
            patch("bot_app.services.card_replace.get_telegram_prefs", fake_prefs),
            patch("bot_app.services.card_replace.safe_send", AsyncMock()),
        ):
            await send_or_replace_card(bot, 42, vacancy_id="v1", text="hi")
    finally:
        reset_current_account_id(token)

    # НЕ 1 — owner из автоюз-фикстуры _fake_default_account_id, а 7 — current_account_id().
    assert seen_account_ids == [7]


_FAKE_ACCOUNT_ROW: dict[str, object] = {
    "id": 99,
    "telegram_user_id": 1,
    "telegram_username": None,
    "telegram_chat_id": 1,
    "role": "owner",
    "status": "active",
}


@pytest.mark.asyncio
async def test_track_progress_gets_default_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakePool:
        async def fetchrow(self, _sql: str, *_args: object) -> dict[str, object]:
            return _FAKE_ACCOUNT_ROW

        async def fetchval(self, _sql: str, *args: object) -> int:
            captured["args"] = args
            return 11

    monkeypatch.setattr(reg, "get_pool", lambda: FakePool())
    assert await reg.track(1, 2, reg.KIND_PROGRESS) == 11
    args = captured["args"]
    assert isinstance(args, tuple)
    # chat_id, message_id, kind, vacancy_id, cleanup_after, account_id
    assert args[2] == reg.KIND_PROGRESS
    assert args[4] is not None


@pytest.mark.asyncio
async def test_track_menu_no_default_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakePool:
        async def fetchrow(self, _sql: str, *_args: object) -> dict[str, object]:
            return _FAKE_ACCOUNT_ROW

        async def fetchval(self, _sql: str, *args: object) -> int:
            captured["args"] = args
            return 12

    monkeypatch.setattr(reg, "get_pool", lambda: FakePool())
    await reg.track(1, 2, reg.KIND_MENU)
    args = captured["args"]
    assert isinstance(args, tuple)
    assert args[4] is None


@pytest.mark.asyncio
async def test_track_service_gets_default_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakePool:
        async def fetchrow(self, _sql: str, *_args: object) -> dict[str, object]:
            return _FAKE_ACCOUNT_ROW

        async def fetchval(self, _sql: str, *args: object) -> int:
            captured["args"] = args
            return 13

    monkeypatch.setattr(reg, "get_pool", lambda: FakePool())
    await reg.track(1, 2, reg.KIND_SERVICE)
    args = captured["args"]
    assert isinstance(args, tuple)
    assert args[4] is not None


@pytest.mark.asyncio
async def test_pop_by_vacancy_empty_and_pg_down(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await reg.pop_by_vacancy(1, reg.KIND_CARD, "") == []
    monkeypatch.setattr(reg, "get_pool", lambda: (_ for _ in ()).throw(RuntimeError("pg")))
    assert await reg.pop_by_vacancy(1, reg.KIND_CARD, "v1") == []
