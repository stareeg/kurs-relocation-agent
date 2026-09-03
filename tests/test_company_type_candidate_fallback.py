"""Этап 6 §6.4 (plans/scoring_precision_2026_08_17.md): `company_types` резюме против
хардкод-таблицы `_COMPANY_TYPE_FRACTION`.

Раньше фолбэк оси «Компания» (когда LLM не определила `company_fit.level`) был одной таблицей
на всех кандидатов — «аутсорс» всегда 0.25, даже если резюме прямо говорит, что кандидат
рассматривает аутсорс. Теперь `candidate_company_types` (из `CandidateProfile.company_types`,
чипы `CANDIDATE_COMPANY_TYPES` в resume-taxonomy.ts) сверяет вакансию с явным предпочтением;
пустой список — прежнее поведение без изменений.
"""

from __future__ import annotations

from core.domains.opportunities.models import (
    BurnoutRisk,
    CompanyFit,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.score_breakdown import COMPANY_WEIGHT, compute_score_breakdown
from core.domains.profile.profile import CandidateProfile, derive_candidate_profile
from core.domains.profile.model import ResumeData


def _score_with_company_type(company_type: str) -> ScoreResult:
    return ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_fit=CompanyFit(level="unknown", reasoning=""),
        company_type=company_type,
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


def test_empty_candidate_company_types_keeps_static_table():
    """Пустой список предпочтений (ничего не отмечено) — поведение не меняется."""
    score = _score_with_company_type("outsource")
    breakdown_none = compute_score_breakdown(score, candidate_company_types=None)
    breakdown_empty = compute_score_breakdown(score, candidate_company_types=[])
    assert breakdown_none["company"] == breakdown_empty["company"]
    # Статическая таблица: outsource = 0.25 → низкий, но не ноль.
    assert breakdown_none["company"] == round(COMPANY_WEIGHT * 0.25)


def test_candidate_accepting_outsource_is_not_penalized_like_default():
    score = _score_with_company_type("outsource")
    default_points = compute_score_breakdown(score)["company"]
    accepted_points = compute_score_breakdown(
        score, candidate_company_types=["Аутсорс"]
    )["company"]
    assert accepted_points > default_points


def test_startup_chip_actually_moves_the_axis():
    """Чип «Стартап» заменил «Валютку» в списке кандидата и, в отличие от неё, мапится на слаг.

    «Валютка» не мапилась ни на один `company_type`, то есть отметка чипа не меняла балл
    вообще — ровно та ручка без потребителя, из-за которой её и убрали из таксономии.
    """
    score = _score_with_company_type("startup")
    default_points = compute_score_breakdown(score)["company"]
    accepted_points = compute_score_breakdown(score, candidate_company_types=["Стартап"])["company"]
    assert accepted_points > default_points


def test_candidate_rejecting_type_scores_below_neutral():
    """Кандидат отметил только «Продукт» — банк, которого нет в списке, получает минус."""
    score = _score_with_company_type("bank")
    breakdown = compute_score_breakdown(score, candidate_company_types=["Продукт"])
    assert breakdown["company"] < round(COMPANY_WEIGHT * 0.55)


def test_unknown_company_type_stays_neutral_regardless_of_preferences():
    score = _score_with_company_type("unknown")
    breakdown = compute_score_breakdown(score, candidate_company_types=["Продукт"])
    assert breakdown["company"] == round(COMPANY_WEIGHT * 0.55)


def test_company_fit_known_ignores_candidate_company_types():
    """Когда LLM смогла определить company_fit.level, фолбэк по company_types не участвует."""
    score = _score_with_company_type("outsource").model_copy(
        update={"company_fit": CompanyFit(level="strong", reasoning="r")}
    )
    breakdown_no_prefs = compute_score_breakdown(score)
    breakdown_with_prefs = compute_score_breakdown(score, candidate_company_types=["Продукт"])
    assert breakdown_no_prefs["company"] == breakdown_with_prefs["company"]


def test_derive_candidate_profile_reads_resume_company_types():
    data = ResumeData()
    data.position.company_types = ["Биг тех", "Продукт"]
    profile = derive_candidate_profile(data)
    assert isinstance(profile, CandidateProfile)
    assert profile.company_types == ["Биг тех", "Продукт"]
