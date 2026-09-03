"""Э2.3: гейты второго трека — две улики → skip-бейдж, одна → WARNING не skip."""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
    VacancyWorkTerms,
)
from core.domains.opportunities.rules import CandidateFormatPrefs, detect_gates
from core.domains.profile.international import InternationalReadiness

_PREFS = CandidateFormatPrefs(
    allows_office=True, allows_hybrid=True, allows_remote=True, travel_is_dealbreaker=False
)
_QUIET = "senior engineer, interesting tasks, strong team, remote worldwide"


def _score(**overrides: object) -> ScoreResult:
    base: dict[str, object] = dict(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )
    base.update(overrides)
    return ScoreResult(**base)  # type: ignore[arg-type]


def _gates(
    score: ScoreResult,
    text: str,
    *,
    terms: VacancyWorkTerms | None = None,
    intl: InternationalReadiness | None = None,
    market_scope: str = "any",
    candidate_city: str = "",
) -> str | None:
    return detect_gates(
        score,
        text,
        format_prefs=_PREFS,
        track="second_job",
        terms=terms,
        intl=intl,
        market_scope=market_scope,
        candidate_city=candidate_city,
        vacancy_id="v-1",
    )


def test_work_auth_two_witnesses_skip() -> None:
    terms = VacancyWorkTerms(residency_required=True)
    badge = _gates(_score(), "must be authorized to work in the region", terms=terms)
    assert badge == "Балл срезан: Право на работу"


def test_work_auth_one_witness_not_skip(caplog: pytest.LogCaptureFixture) -> None:
    terms = VacancyWorkTerms(residency_required=True)
    with caplog.at_level("WARNING"):
        badge = _gates(_score(), _QUIET, terms=terms)
    assert badge is None
    assert any("улики разошлись" in r.message for r in caplog.records)


def test_exclusivity_two_witnesses_skip() -> None:
    terms = VacancyWorkTerms(exclusivity="required")
    badge = _gates(_score(), "no moonlighting allowed for this role", terms=terms)
    assert badge == "Балл срезан: Эксклюзивность"


def test_exclusivity_one_witness_not_skip(caplog: pytest.LogCaptureFixture) -> None:
    terms = VacancyWorkTerms(exclusivity="required")
    with caplog.at_level("WARNING"):
        badge = _gates(_score(), _QUIET, terms=terms)
    assert badge is None
    assert any("Эксклюзивность" in r.message for r in caplog.records)


def test_presence_two_witnesses_skip() -> None:
    terms = VacancyWorkTerms(geo_scope="single_city")
    badge = _gates(
        _score(work_city="Berlin"),
        "on-site 5 days in the office hybrid 3",
        terms=terms,
        candidate_city="Москва",
    )
    assert badge == "Балл срезан: Физическое присутствие"


def test_presence_one_witness_not_skip(caplog: pytest.LogCaptureFixture) -> None:
    terms = VacancyWorkTerms(geo_scope="single_city")
    with caplog.at_level("WARNING"):
        badge = _gates(_score(), _QUIET, terms=terms, candidate_city="Москва")
    assert badge is None
    assert any("Физическое присутствие" in r.message for r in caplog.records)


def test_overlap_window_gate() -> None:
    terms = VacancyWorkTerms(overlap_hours_required=8, hiring_geo=["EMEA"])
    intl = InternationalReadiness(overlap={"EMEA": 2})
    badge = _gates(_score(), _QUIET, terms=terms, intl=intl)
    assert badge == "Балл срезан: Окно пересечения"


def test_overlap_near_miss_not_gate() -> None:
    terms = VacancyWorkTerms(overlap_hours_required=5, hiring_geo=["EMEA"])
    intl = InternationalReadiness(overlap={"EMEA": 3})
    badge = _gates(_score(), _QUIET, terms=terms, intl=intl)
    assert badge is None


def test_other_profession_gate() -> None:
    score = _score(
        grade_match=GradeMatch(
            level="off_profile", off_profile_kind="other_profession", reasoning="r"
        )
    )
    badge = _gates(score, _QUIET, terms=VacancyWorkTerms())
    assert badge == "Балл срезан: Другая профессия"


def test_far_below_is_not_second_job_gate() -> None:
    score = _score(grade_match=GradeMatch(level="far_below", reasoning="r"))
    badge = _gates(score, _QUIET, terms=VacancyWorkTerms())
    assert badge is None
