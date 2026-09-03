"""Очередь подтверждения (Фаза 3.3 анкета + Фаза 3.4 простое подтверждение письма) — общая
`jobs.anketa`, `confirm_anketa`/`reject_anketa`/`list_pending_anketas` не завязаны на наличие
вопросов (пустой `questions` — режим «Тест» без анкеты, plans/auto_apply_roadmap_2026_08_17.md
§3.4)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.app.scenarios import auto_apply as scenario
from core.domains.opportunities.jobs import Job


def _job_with_anketa(status: str, *, questions: list | None = None) -> Job:
    return Job(
        id=1,
        vacancy_id="v1",
        vacancy_text="x" * 60,
        anketa={
            "status": status,
            "platform": "hh",
            "questions": questions or [],
            "answers": [],
            "requested_at": "2026-08-18T00:00:00+00:00",
            "resolved_at": None,
        },
    )


async def test_confirm_letter_only_pending_moves_to_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _job_with_anketa("pending")
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=pending))
    update_mock = AsyncMock(return_value=_job_with_anketa("approved"))
    monkeypatch.setattr(scenario, "update_job_anketa", update_mock)

    result = await scenario.confirm_anketa(1, answers=[], account_id=9)

    assert result is not None
    saved = update_mock.await_args.kwargs["anketa"]
    assert saved["status"] == "approved"
    assert saved["questions"] == []


async def test_reject_letter_only_pending_moves_to_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = _job_with_anketa("pending")
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=pending))
    update_mock = AsyncMock(return_value=_job_with_anketa("rejected"))
    monkeypatch.setattr(scenario, "update_job_anketa", update_mock)

    result = await scenario.reject_anketa(1, account_id=9)

    assert result is not None
    saved = update_mock.await_args.kwargs["anketa"]
    assert saved["status"] == "rejected"


async def test_confirm_missing_job_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=None))
    result = await scenario.confirm_anketa(999, answers=[], account_id=9)
    assert result is None


async def test_confirm_job_without_pending_anketa_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = Job(id=1, vacancy_id="v1", vacancy_text="x" * 60, anketa=None)
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=job))
    result = await scenario.confirm_anketa(1, answers=[], account_id=9)
    assert result is None


async def test_list_pending_includes_letter_only_and_anketa_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    letter_only = _job_with_anketa("pending")
    with_anketa = _job_with_anketa("pending", questions=[{"id": "q1", "text": "?", "type": "text"}])
    other_platform = _job_with_anketa("pending")
    other_platform.anketa["platform"] = "getmatch"
    approved = _job_with_anketa("approved")
    no_anketa = Job(id=5, vacancy_id="v5", vacancy_text="x" * 60, anketa=None)

    monkeypatch.setattr(
        scenario,
        "list_jobs",
        AsyncMock(return_value=[letter_only, with_anketa, other_platform, approved, no_anketa]),
    )

    result = await scenario.list_pending_anketas("hh", status="pending", account_id=9)

    assert result == [letter_only, with_anketa]
