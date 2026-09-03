"""Этап 5 §5.1 (plans/scoring_precision_2026_08_17.md, D7): версия рубрики скоринга.

Веса пересчитываются от резюме на каждом скоринге — без версии сравнение overall_score двух
вакансий, посчитанных в разные дни, сравнивает числа из разных линеек. `weights_version` —
хэш-отпечаток эффективной рубрики (веса + role_kind + пороги), который штампует каждый
пересчёт (`apply_calibration`/`recompute_salary_axis`).
"""

from __future__ import annotations

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.rules import CandidateFormatPrefs, apply_calibration
from core.domains.opportunities.score_breakdown import SECOND_JOB_WEIGHTS
from core.domains.opportunities.weights_version import compute_weights_version

_PREFS = CandidateFormatPrefs(
    allows_office=True, allows_hybrid=True, allows_remote=True, travel_is_dealbreaker=False
)


def _score() -> ScoreResult:
    return ScoreResult(
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


def test_compute_weights_version_stable_regardless_of_key_order():
    a = compute_weights_version(
        {"salary": 20, "work_format": 20, "grade_match": 10, "role_content": 25,
         "management": 15, "company": 10},
        role_kind="mixed",
        thresholds=(80, 65, 45),
    )
    b = compute_weights_version(
        {"company": 10, "management": 15, "role_content": 25, "grade_match": 10,
         "work_format": 20, "salary": 20},
        role_kind="mixed",
        thresholds=(80, 65, 45),
    )
    assert a == b


def test_compute_weights_version_changes_with_weights():
    base = {"salary": 20, "work_format": 20, "grade_match": 10, "role_content": 25,
            "management": 15, "company": 10}
    a = compute_weights_version(base, role_kind="mixed", thresholds=(80, 65, 45))
    changed = {**base, "work_format": 21, "grade_match": 9}
    b = compute_weights_version(changed, role_kind="mixed", thresholds=(80, 65, 45))
    assert a != b


def test_compute_weights_version_changes_with_role_kind():
    base = {"salary": 20, "work_format": 20, "grade_match": 10, "role_content": 25,
            "management": 15, "company": 10}
    a = compute_weights_version(base, role_kind="mixed", thresholds=(80, 65, 45))
    b = compute_weights_version(base, role_kind="hands_on", thresholds=(80, 65, 45))
    assert a != b


def test_apply_calibration_stamps_weights_version():
    result = apply_calibration(
        _score(), "текст вакансии", format_prefs=_PREFS, role_kind="mixed"
    )
    assert result.weights_version != ""


def test_apply_calibration_same_inputs_give_same_version():
    """Детерминизм: одинаковые веса/role_kind на разных вызовах — одна и та же версия. Это и есть
    гарантия, на которой стоит перескор (Этап 5 §5.2) — версия сравнима между запусками."""
    weights = {"salary": 20, "work_format": 20, "grade_match": 10, "role_content": 25,
               "management": 15, "company": 10}
    a = apply_calibration(
        _score(), "текст A", format_prefs=_PREFS, role_kind="mixed", scoring_weights=weights
    )
    b = apply_calibration(
        _score(),
        "текст B (другой)",
        format_prefs=_PREFS,
        role_kind="mixed",
        scoring_weights=weights,
    )
    assert a.weights_version == b.weights_version


def test_apply_calibration_different_weights_give_different_version():
    weights_a = {"salary": 20, "work_format": 20, "grade_match": 10, "role_content": 25,
                 "management": 15, "company": 10}
    weights_b = {**weights_a, "work_format": 17, "grade_match": 13}
    a = apply_calibration(
        _score(), "текст", format_prefs=_PREFS, role_kind="mixed", scoring_weights=weights_a
    )
    b = apply_calibration(
        _score(), "текст", format_prefs=_PREFS, role_kind="mixed", scoring_weights=weights_b
    )
    assert a.weights_version != b.weights_version


def test_compute_weights_version_track_changes_hash_only_for_second_job():
    base = {
        "salary": 20,
        "work_format": 20,
        "grade_match": 10,
        "role_content": 25,
        "management": 15,
        "company": 10,
    }
    without = compute_weights_version(base, role_kind="mixed", thresholds=(80, 65, 45))
    primary = compute_weights_version(
        base, role_kind="mixed", thresholds=(80, 65, 45), track="primary"
    )
    second = compute_weights_version(
        SECOND_JOB_WEIGHTS, role_kind="mixed", thresholds=(80, 65, 45), track="second_job"
    )
    assert without == primary
    assert second != primary
