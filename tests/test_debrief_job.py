"""DBR-2: разбор транскрипта — фоновая задача + опрос статуса вместо синхронного ожидания LLM."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import api.routers.preparation.debrief as debrief_router
from api.schemas import DebriefAnalyzeRequest
from api.security import AccountContext
from core.app.scenarios.debrief import DebriefResult as ScenarioDebriefResult
from core.domains.preparation.models import DebriefAnalysis
from core.kernel.errors import UpstreamError

_ACCOUNT = AccountContext(account_id=1, telegram_user_id=1, telegram_username=None, role="owner")


@pytest.fixture(autouse=True)
def _clean_jobs():
    debrief_router._JOBS.clear()
    yield
    debrief_router._JOBS.clear()


def _analysis() -> DebriefAnalysis:
    return DebriefAnalysis(
        questions_asked=[],
        weak_answers=[],
        strong_answers=[],
        topics_to_study=[],
        competency_map=[],
        honest_notes=[],
        interview_format="other",
        next_steps_signal="unknown",
        overall_impression=5,
        summary="ok",
    )


def _scenario_result(vacancy_id: str) -> ScenarioDebriefResult:
    return ScenarioDebriefResult(vacancy_id=vacancy_id, stage="tech", analysis=_analysis())


async def _wait_terminal(vacancy_id: str, job_id: str, *, tries: int = 200):
    for _ in range(tries):
        status = await debrief_router.analyze_status(vacancy_id, job_id)
        if status.status != "running":
            return status
        await asyncio.sleep(0)
    raise AssertionError("job не завершился (тест завис бы вечно как раз то, что чиним)")


async def test_start_analyze_rejects_short_transcript_without_creating_job() -> None:
    body = DebriefAnalyzeRequest(transcript="коротко")
    with pytest.raises(HTTPException) as exc_info:
        await debrief_router.start_analyze("vac-1", body, account=_ACCOUNT)
    assert exc_info.value.status_code == 400
    assert not debrief_router._JOBS


async def test_job_lifecycle_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_analyze(
        ref, *, stage, transcript, account_id, interview_stage_id=None, attachment_ids=()
    ):
        return _scenario_result(ref.vacancy_id)

    monkeypatch.setattr(debrief_router, "analyze", fake_analyze)

    body = DebriefAnalyzeRequest(transcript="достаточно длинный транскрипт для теста разбора")
    started = await debrief_router.start_analyze("vac-1", body, account=_ACCOUNT)
    assert started.status == "running"
    assert started.job_id in debrief_router._JOBS

    status = await _wait_terminal("vac-1", started.job_id)
    assert status.status == "done"
    assert status.error is None
    assert status.result is not None
    assert status.result.vacancy_id == "vac-1"


async def test_job_lifecycle_error_surfaces_message(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_analyze(
        ref, *, stage, transcript, account_id, interview_stage_id=None, attachment_ids=()
    ):
        raise UpstreamError("модель долго думает")

    monkeypatch.setattr(debrief_router, "analyze", fake_analyze)

    body = DebriefAnalyzeRequest(transcript="достаточно длинный транскрипт для теста разбора")
    started = await debrief_router.start_analyze("vac-1", body, account=_ACCOUNT)

    status = await _wait_terminal("vac-1", started.job_id)
    assert status.status == "error"
    assert status.result is None
    assert status.error == "модель долго думает"


async def test_analyze_status_unknown_job_is_404() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await debrief_router.analyze_status("vac-1", "не-существует")
    assert exc_info.value.status_code == 404
