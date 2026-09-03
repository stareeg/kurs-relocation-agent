"""Шаг 15: пороги recommendation под относительную шкалу (MAYBE_MIN=45).

Идеал → 100 / strong_apply; типичное хорошее → apply (65-79);
явный мисматч → skip (<45). Два профиля: владелец (hands_on) и PM (management).
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.rules import (
    APPLY_MIN,
    MAYBE_MIN,
    STRONG_APPLY_MIN,
    CandidateFormatPrefs,
    _recommendation_from_score,
    apply_calibration,
)
from core.domains.opportunities.models import (
    BurnoutRisk,
    CompanyFit,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.score_breakdown import compute_score_breakdown

_NEUTRAL_PREFS = CandidateFormatPrefs(
    allows_office=True,
    allows_hybrid=True,
    allows_remote=True,
    travel_is_dealbreaker=False,
)

_VACANCY = "Удалённо. Product-команда. Без командировок."


def _make_score(
    *,
    salary_meets_min: bool,
    format_level: str,
    grade_level: str,
    role_score: int,
    burnout_level: str,
    company_level: str,
    company_type: str = "product",
) -> ScoreResult:
    return ScoreResult(
        overall_score=50,
        recommendation="maybe",
        remote_abroad_compat=RemoteAbroadCompat(level=format_level, reasoning="r"),
        grade_match=GradeMatch(level=grade_level, reasoning="r"),
        salary=SalaryInfo(meets_min=salary_meets_min, value_or_range="x", note=""),
        role_content_match=RoleContentMatch(score=role_score, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level=burnout_level, reasoning="r"),
        company_fit=CompanyFit(level=company_level, reasoning="r"),
        company_type=company_type,  # type: ignore[arg-type]
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


def _calibrate(score: ScoreResult, *, role_kind: str) -> ScoreResult:
    return apply_calibration(
        score,
        _VACANCY,
        company_adjustments=[],
        list_rules=[],
        format_prefs=_NEUTRAL_PREFS,
        role_kind=role_kind,
    )


# --- границы констант ---


def test_recommendation_band_edges():
    assert _recommendation_from_score(STRONG_APPLY_MIN) == "strong_apply"
    assert _recommendation_from_score(APPLY_MIN) == "apply"
    assert _recommendation_from_score(APPLY_MIN - 1) == "maybe"
    assert _recommendation_from_score(MAYBE_MIN) == "maybe"
    assert _recommendation_from_score(MAYBE_MIN - 1) == "skip"


# --- арифметика профилей ---

# Владелец (hands_on): идеал 100; нормально ~78; не то ~43.
# PM (management): идеал 100; нормально ~74; не то ~44.


@pytest.mark.parametrize(
    "role_kind,case,kwargs,expected_rec,score_lo,score_hi",
    [
        (
            "hands_on",
            "ideal",
            dict(
                salary_meets_min=True,
                format_level="ideal",
                grade_level="match",
                role_score=100,
                burnout_level="low",
                company_level="strong",
            ),
            "strong_apply",
            100,
            100,
        ),
        (
            "hands_on",
            "normal",
            dict(
                salary_meets_min=True,
                format_level="risky",
                grade_level="match",
                role_score=70,
                burnout_level="medium",
                company_level="ok",
            ),
            "apply",
            65,
            79,
        ),
        (
            "hands_on",
            "mismatch",
            dict(
                salary_meets_min=False,
                format_level="risky",
                grade_level="slightly_below",
                role_score=40,
                burnout_level="high",
                company_level="weak",
            ),
            "skip",
            0,
            44,
        ),
        (
            "management",
            "ideal",
            dict(
                salary_meets_min=True,
                format_level="ok",
                grade_level="match",
                role_score=100,
                burnout_level="high",
                company_level="strong",
            ),
            "strong_apply",
            100,
            100,
        ),
        (
            "management",
            "normal",
            dict(
                salary_meets_min=True,
                format_level="risky",
                grade_level="slightly_below",
                role_score=75,
                burnout_level="medium",
                company_level="ok",
            ),
            "apply",
            65,
            79,
        ),
        (
            "management",
            "mismatch",
            dict(
                salary_meets_min=False,
                format_level="risky",
                grade_level="slightly_below",
                role_score=35,
                burnout_level="low",
                company_level="weak",
            ),
            "skip",
            0,
            44,
        ),
    ],
)
def test_profile_synthetic_land_in_expected_band(
    role_kind, case, kwargs, expected_rec, score_lo, score_hi
):
    score = _make_score(**kwargs)
    raw = sum(compute_score_breakdown(score, role_kind=role_kind).values())
    assert score_lo <= raw <= score_hi, f"{role_kind}/{case}: breakdown={raw}"

    result = _calibrate(score, role_kind=role_kind)
    assert result.gate_triggered is None
    assert result.overall_score == raw
    assert result.recommendation == expected_rec
    assert _recommendation_from_score(result.overall_score) == expected_rec
