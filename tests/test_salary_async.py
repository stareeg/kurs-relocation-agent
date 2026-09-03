"""Регресс: payload с невалидным `score` не должен ронять задачу до входа в
`_run_salary_estimate` — иначе очередь тихо сдаётся после ретраев, и `estimate_pending`
остаётся True навсегда (баг «вилка навсегда виснет на "оценка…"», см. salary_async.py).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.domains.opportunities import salary_async
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)


def _score_result() -> ScoreResult:
    return ScoreResult(
        overall_score=70,
        recommendation="apply",  # type: ignore[arg-type]
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


@pytest.mark.asyncio
async def test_invalid_score_context_degrades_gracefully(monkeypatch):
    calls: list[object] = []

    async def fake_run(vacancy_id, vacancy_text, score, *, account_id):
        calls.append(score)

    monkeypatch.setattr(salary_async, "_run_salary_estimate", fake_run)

    await salary_async.run_salary_estimate_from_payload(
        {
            "vacancy_id": "vac-1",
            "vacancy_text": "text",
            "score": {"not": "a valid ScoreResult"},
            "account_id": 1,
        }
    )

    assert calls == [None]


@pytest.mark.asyncio
async def test_valid_score_context_is_parsed(monkeypatch):
    calls: list[object] = []

    async def fake_run(vacancy_id, vacancy_text, score, *, account_id):
        calls.append(score)

    monkeypatch.setattr(salary_async, "_run_salary_estimate", fake_run)

    valid = _score_result()
    await salary_async.run_salary_estimate_from_payload(
        {
            "vacancy_id": "vac-1",
            "vacancy_text": "text",
            "score": valid.model_dump(mode="json"),
            "account_id": 1,
        }
    )

    assert len(calls) == 1
    assert isinstance(calls[0], ScoreResult)


@pytest.mark.asyncio
async def test_background_range_rescored_into_the_saved_score(monkeypatch):
    """Этап 2: фоновая вилка не только пишется в salary — она пересчитывает ось балла.

    Без этого рампа §2.1 не работала бы на 81% вакансий прода: на момент `POST /score` чисел
    ещё нет, ось стоит нейтрально, а старый путь сохранял тот же overall_score.
    """
    from core.domains.opportunities.salary_estimator import SalaryEstimate
    from core.domains.profile import structured_store
    from core.domains.profile.model import DesiredPosition, ResumeData

    base = _score_result().model_copy(
        update={
            "score_breakdown": {
                "salary": 11,
                "work_format": 20,
                "grade_match": 15,
                "role_content": 12,
                "management": 12,
                "company": 10,
            },
            "salary": SalaryInfo(meets_min=True, value_or_range="", note="", estimate_pending=True),
        }
    )
    job = SimpleNamespace(
        id=1, vacancy_id="vac-1", score=base.model_dump(mode="json"), is_archived=False
    )
    saved: dict[str, object] = {}

    async def fake_estimate(vacancy_text, score, *, profile=None):
        return SalaryEstimate(
            salary_min=560_000,
            salary_max=640_000,
            meets_min=True,
            note="по наблюдениям сегмента",
            confidence="high",
            source="corpus",
        )

    async def fake_get_job(vacancy_id, *, account_id, db=None):
        return job

    async def fake_update(vacancy_id, **kwargs):
        saved.update(kwargs)

    async def fake_resume(account_id, db=None):
        return ResumeData(
            position=DesiredPosition(salary_min=400_000, salary_comfortable=500_000)
        )

    monkeypatch.setattr(salary_async, "estimate_salary", fake_estimate)
    monkeypatch.setattr(salary_async, "get_job_by_vacancy_id", fake_get_job)
    monkeypatch.setattr(salary_async, "update_job_score", fake_update)
    monkeypatch.setattr(salary_async, "publish_vacancy_scored", lambda **kwargs: None)
    monkeypatch.setattr(structured_store, "read_resume_data_for_account", fake_resume)

    await salary_async._run_salary_estimate("vac-1", "текст вакансии", base, account_id=1)

    assert saved["overall_score"] > base.overall_score
    assert saved["score_json"]["score_breakdown"]["salary"] > 11
    assert saved["score_json"]["score_breakdown"]["work_format"] == 20
    assert saved["salary_json"]["estimated_min"] == 560_000


def test_payload_not_pending_when_salary_already_there() -> None:
    assert salary_async._merged_has_salary(
        {"estimate_pending": True, "estimated_range": "300–400к", "source": "llm"}
    )
    assert salary_async._merged_has_salary({"source": "explicit", "value_or_range": "400 000"})
    assert not salary_async._merged_has_salary(
        {"estimate_pending": True, "source": "none", "estimated_range": "", "value_or_range": ""}
    )


@pytest.mark.asyncio
async def test_missing_vacancy_id_still_raises():
    with pytest.raises(ValueError):
        await salary_async.run_salary_estimate_from_payload(
            {"vacancy_text": "text", "score": {}, "account_id": 1}
        )


@pytest.mark.asyncio
async def test_missing_account_id_still_raises():
    with pytest.raises(ValueError):
        await salary_async.run_salary_estimate_from_payload(
            {"vacancy_id": "vac-1", "vacancy_text": "text", "score": {}}
        )
