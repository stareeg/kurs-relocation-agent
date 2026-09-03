"""Этап 7 §7.3: превью «топ-20 при гипотетических весах» — ничего не пишет в БД."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities import rescore
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.profile.model import DesiredPosition, ResumeData, SearchCriteria


def _score(*, role_content_score: int, meets_min: bool) -> ScoreResult:
    return ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=meets_min, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=role_content_score, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


def _job(job_id: int, vacancy_id: str, score: ScoreResult) -> Job:
    return Job(
        id=job_id,
        vacancy_id=vacancy_id,
        vacancy_text="текст вакансии, формат работы: удалённо",
        company="ACME",
        source="hh",
        overall_score=score.overall_score,
        recommendation=score.recommendation,
        score=score.model_dump(mode="json"),
    )


@pytest.fixture(autouse=True)
def _patch_resume_context(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resume(_account_id: int, db: object | None = None) -> ResumeData:
        return ResumeData(position=DesiredPosition(schedule=["Удалённо"]), search_criteria=SearchCriteria())

    async def fake_manual_rules(_account_id: int) -> list:
        return []

    async def fake_skill_overlap(_vacancy_id: str | None, _profile: Any) -> None:
        return None

    monkeypatch.setattr(rescore, "read_resume_data_for_account", fake_resume)
    monkeypatch.setattr(rescore, "load_manual_company_adjustments", fake_manual_rules)
    monkeypatch.setattr(rescore, "load_list_company_adjustments", lambda _data: [])
    monkeypatch.setattr(rescore, "_load_skill_overlap", fake_skill_overlap)


async def test_simulate_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    role_heavy = _job(1, "vac-role", _score(role_content_score=90, meets_min=False))
    salary_heavy = _job(2, "vac-salary", _score(role_content_score=10, meets_min=True))

    async def fake_list_jobs(*, account_id: int) -> list[Job]:
        return [role_heavy, salary_heavy]

    monkeypatch.setattr(rescore, "list_jobs_for_rescore", fake_list_jobs)

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("simulate не должен писать в БД")

    monkeypatch.setattr(rescore, "update_job_score", _boom)
    monkeypatch.setattr(rescore, "publish_vacancy_scored", _boom)

    rows = await rescore.simulate_weight_override(account_id=1, overrides={"role_content": 0})
    assert len(rows) == 2


async def test_simulate_reorders_and_surfaces_entries_and_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """role_content — самая тяжёлая ось по умолчанию (25): при полной ставке на неё role_heavy
    сейчас впереди. Обнулив её вес, salary_heavy должен обогнать — превью обязано показать ОБЕИХ
    (кто вошёл бы в топ, кто выпал), не только перестановку внутри одного и того же набора."""
    role_heavy = _job(1, "vac-role", _score(role_content_score=90, meets_min=False))
    salary_heavy = _job(2, "vac-salary", _score(role_content_score=10, meets_min=True))

    async def fake_list_jobs(*, account_id: int) -> list[Job]:
        return [role_heavy, salary_heavy]

    monkeypatch.setattr(rescore, "list_jobs_for_rescore", fake_list_jobs)
    monkeypatch.setattr(rescore, "update_job_score", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(rescore, "publish_vacancy_scored", lambda *a, **k: (_ for _ in ()).throw(AssertionError))

    rows = await rescore.simulate_weight_override(
        account_id=1, overrides={"role_content": 0}, limit=1
    )
    by_id = {r.vacancy_id: r for r in rows}
    assert set(by_id) == {"vac-role", "vac-salary"}
    assert by_id["vac-role"].before_rank == 1
    assert by_id["vac-salary"].after_rank == 1
    # role_heavy теряет позицию под новыми весами — доказывает, что override реально применился.
    assert by_id["vac-role"].after_rank != by_id["vac-role"].before_rank
