"""Этап 6 §6.2: `persist_scored_with_repo` штампует `Job.competition` из полей `VacancyInput`.

Никакого нового async-параметра не заведено (в отличие от `remote` — тот LLM, этот нет):
`_build_job` считает `compute_competition_insight` синхронно прямо на входных vac.* полях.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.domains.opportunities.jobs import ApplicationStage, Job, JobLink
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
    VacancyInput,
)
from core.domains.opportunities.persist import persist_scored_with_repo
from core.kernel import ports


@dataclass
class _MemJobsRepo:
    jobs: dict[str, Job] = field(default_factory=dict)
    stages: list[ApplicationStage] = field(default_factory=list)
    _seq: int = 0

    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    async def save(self, job: Job, *, preserve_status: bool = False) -> Job:
        _ = preserve_status
        saved = job.model_copy(update={"id": job.id or self._next_id()})
        self.jobs[saved.vacancy_id or str(saved.id)] = saved
        return saved

    async def add_stage(
        self, job_id: int, stage: str, *, source: str = "manual", applied_at: str | None = None
    ) -> ApplicationStage:
        _ = applied_at
        st = ApplicationStage(id=self._next_id(), job_id=job_id, stage=stage, source=source)
        self.stages.append(st)
        return st

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None:
        return self.jobs.get(vacancy_id)

    async def find_duplicate_candidates(self, tokens: list[str], *, limit: int = 20) -> list[Job]:
        return []

    async def add_job_link(self, job_id: int, **kwargs) -> JobLink:
        raise AssertionError("дедуп не должен сработать в этих тестах")

    async def enrich_job(self, job_id: int, **kwargs) -> Job | None:
        raise AssertionError("дедуп не должен сработать в этих тестах")


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def _sample_score() -> ScoreResult:
    return ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="v",
    )


async def test_competition_is_unknown_without_total_responses():
    repo = _MemJobsRepo()
    vac = VacancyInput(
        source="vacancy_page",
        vacancy_id="1",
        text="A" * 60,
        title="T",
    )
    result = await persist_scored_with_repo(vac, _sample_score(), repo=repo, account_id=1)
    assert result.job.competition == {
        "level": "unknown",
        "responses_per_day": None,
        "age_days": None,
        "reasoning": "нет данных о числе откликов на вакансию",
    }


async def test_competition_is_computed_from_vacancy_input_fields():
    repo = _MemJobsRepo()
    vac = VacancyInput(
        source="vacancy_page",
        vacancy_id="2",
        text="A" * 60,
        title="T",
        total_responses=2,
        published_at="1 января 2020",
        letter_required=False,
    )
    result = await persist_scored_with_repo(vac, _sample_score(), repo=repo, account_id=1)
    assert result.job.competition is not None
    assert result.job.competition["level"] == "favorable"
    assert result.job.competition["age_days"] is not None and result.job.competition["age_days"] > 0
