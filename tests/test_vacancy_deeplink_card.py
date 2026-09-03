"""TB-5.5: deep-link start=vac_<id> → карточка скоринга (не текстовые ссылки)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot_app.handlers import menu as menu_mod
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)


def _score_dict() -> dict:
    score = ScoreResult(
        overall_score=88,
        recommendation="strong_apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="300k", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="ok",
    )
    return score.model_dump()


def _message() -> MagicMock:
    msg = MagicMock()
    msg.bot = AsyncMock()
    msg.chat.id = 42
    msg.answer = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_deeplink_with_score_sends_score_card() -> None:
    job = Job(
        vacancy_text="длинный текст вакансии " * 20,
        company="Acme",
        title="PM",
        vacancy_id="hh_1",
        overall_score=88,
        score=_score_dict(),
    )
    send_card = AsyncMock()
    show = AsyncMock()

    with (
        patch.object(menu_mod, "get_job_by_vacancy_id", AsyncMock(return_value=job)),
        patch.object(menu_mod, "resolve_owner_account_id", AsyncMock(return_value=1)),
        patch.object(menu_mod, "send_typing", AsyncMock()),
        patch.object(menu_mod, "send_or_replace_score_card", send_card),
        patch.object(menu_mod, "show_menu_for", show),
        patch.object(menu_mod, "job_record_needs_vacancy_text", return_value=False),
    ):
        await menu_mod._open_vacancy_deeplink(_message(), "hh_1")

    send_card.assert_awaited_once()
    kwargs = send_card.await_args.kwargs
    assert kwargs["job"] is job
    assert kwargs["score"].overall_score == 88
    assert kwargs["header"] == "Вакансия из расширения"
    show.assert_awaited_once()
    assert show.await_args.args[1].kind == "after_score"


@pytest.mark.asyncio
async def test_deeplink_without_score_keeps_text_fallback() -> None:
    job = Job(
        vacancy_text="x",
        company="Acme",
        title="PM",
        vacancy_id="hh_2",
        overall_score=None,
        score={},
    )
    msg = _message()
    send_card = AsyncMock()

    with (
        patch.object(menu_mod, "get_job_by_vacancy_id", AsyncMock(return_value=job)),
        patch.object(menu_mod, "resolve_owner_account_id", AsyncMock(return_value=1)),
        patch.object(menu_mod, "send_typing", AsyncMock()),
        patch.object(menu_mod, "send_or_replace_score_card", send_card),
        patch.object(menu_mod, "show_menu_for", AsyncMock()),
        patch.object(
            menu_mod,
            "get_bot_settings",
            return_value=SimpleNamespace(web_url="https://example.test"),
        ),
        patch.object(menu_mod, "job_record_needs_vacancy_text", return_value=True),
    ):
        await menu_mod._open_vacancy_deeplink(msg, "hh_2")

    send_card.assert_not_awaited()
    msg.answer.assert_awaited_once()
    body = msg.answer.await_args.args[0]
    assert "Acme" in body
    assert "example.test/jobs/hh_2" in body


@pytest.mark.asyncio
async def test_deeplink_missing_job_idle_menu() -> None:
    msg = _message()
    show = AsyncMock()

    with (
        patch.object(menu_mod, "get_job_by_vacancy_id", AsyncMock(return_value=None)),
        patch.object(menu_mod, "send_typing", AsyncMock()),
        patch.object(menu_mod, "show_menu_for", show),
    ):
        await menu_mod._open_vacancy_deeplink(msg, "missing")

    msg.answer.assert_awaited_once()
    assert "ещё не в системе" in msg.answer.await_args.args[0]
    assert show.await_args.args[1].kind == "idle"
