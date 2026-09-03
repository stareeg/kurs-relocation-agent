"""Этап 1 §1.1–1.2 (plans/scoring_precision_2026_08_17.md): формат-гейт по двум уликам.

До Этапа 1 гейт формата читал только регекс по строке «формат работы», хотя
instructions.md §«Жёсткие гейты» объявляла условием `remote_abroad_compat.level == "blocker"`.
На проде это давало расхождение в обе стороны: 21 ложный гейт из 58 (штатная формулировка hh
«на месте работодателя или гибрид» читалась как офис-only) и 51 непойманный blocker из 91.
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.rules import (
    CandidateFormatPrefs,
    apply_calibration,
    compute_adjustments,
    detect_gates,
    evaluate_format,
)
from core.domains.opportunities.rules import _is_hybrid_only, _is_office_only

# Резюме владельца в этих тестах не участвует — форматы задаём явно (иначе гейты зависят
# от локального resume_data.json).
_HYBRID_REMOTE = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=True,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
_REMOTE_ONLY = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
_OFFICE_OK = CandidateFormatPrefs(
    allows_office=True,
    allows_hybrid=True,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
_EMPTY_SCHEDULE = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=False,
    travel_is_dealbreaker=False,
)


def _score(*, format_level: str = "ok") -> ScoreResult:
    return ScoreResult(
        overall_score=80,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level=format_level, reasoning="r"),
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


# --- §1.1: регекс по строке «формат работы» ---


@pytest.mark.parametrize(
    ("line", "office_only", "hybrid_only"),
    [
        # Штатная формулировка hh для гибрида — главный источник ложных гейтов (21 из 58).
        ("формат работы: на месте работодателя или гибрид", False, True),
        ("формат работы: на месте работодателя", True, False),
        ("формат работы: гибрид", False, True),
        ("формат работы: на месте работодателя, удалённо или гибрид", False, False),
        ("формат работы: удалённо", False, False),
        ("формат работы: hybrid", False, True),
    ],
)
def test_format_line_classification(line: str, office_only: bool, hybrid_only: bool):
    assert _is_office_only(line) is office_only
    assert _is_hybrid_only(line) is hybrid_only


# --- §1.2: гейт согласован с вердиктом модели ---

_OFFICE_JD = "формат работы: на месте работодателя\nсеньор в офис 5/5"
_HYBRID_JD = "формат работы: на месте работодателя или гибрид\nсеньор"
_NEUTRAL_JD = "формат работы: удалённо\nсеньор, без ограничений"


@pytest.mark.parametrize(
    ("level", "text", "gate", "delta"),
    [
        # blocker + регекс согласен → гейт (как и раньше).
        ("blocker", _OFFICE_JD, True, 0),
        # blocker, регекс молчит → всё равно гейт: модель прочитала текст лучше регекса
        # (51 непойманный blocker из 91 на проде).
        ("blocker", _NEUTRAL_JD, True, 0),
        # регекс кричит «офис», модель говорит «формат подходит» → не гейт, мягкий минус.
        ("ok", _OFFICE_JD, False, -8),
        ("ideal", _OFFICE_JD, False, -8),
        # risky → мягкий минус, не гейт (11 ложных гейтов из 58).
        ("risky", _OFFICE_JD, False, -5),
        # Гибрид в строке формата больше не читается как офис-only.
        ("ok", _HYBRID_JD, False, 0),
        ("risky", _HYBRID_JD, False, 0),
        # Ничего подозрительного — тишина.
        ("ok", _NEUTRAL_JD, False, 0),
    ],
)
def test_evaluate_format_two_pieces_of_evidence(level: str, text: str, gate: bool, delta: int):
    verdict = evaluate_format(level, text, _REMOTE_ONLY)
    assert verdict.gate is gate
    assert verdict.delta == delta


def test_hybrid_jd_is_not_gated_for_candidate_who_allows_hybrid():
    """Ровно кейс прода: в резюме «Гибрид, Удалённо», в вакансии «на месте или гибрид»."""
    result = apply_calibration(
        _score(format_level="ok"),
        _HYBRID_JD,
        format_prefs=_HYBRID_REMOTE,
        role_kind="mixed",
    )
    assert result.gate_triggered is None
    assert result.recommendation != "skip"
    assert result.adjustments == []


def test_hybrid_jd_still_costs_candidate_who_does_not_allow_hybrid():
    """Гибрид-only вне допустимых форматов — мягкий минус (−8), а не жёсткий гейт."""
    adj = compute_adjustments(
        _score(format_level="risky"),
        _HYBRID_JD,
        format_prefs=_REMOTE_ONLY,
    )
    assert [(a.delta, a.reason) for a in adj] == [(-8, "гибрид вне допустимых форматов резюме")]


def test_model_says_ok_but_jd_says_office_gives_soft_minus_not_gate():
    result = apply_calibration(
        _score(format_level="ok"),
        _OFFICE_JD,
        format_prefs=_REMOTE_ONLY,
        role_kind="mixed",
    )
    assert result.gate_triggered is None
    assert result.recommendation != "skip"
    assert any("расхождение" in a.reason for a in result.adjustments)


def test_blocker_without_office_regex_is_gated():
    result = apply_calibration(
        _score(format_level="blocker"),
        _NEUTRAL_JD,
        format_prefs=_REMOTE_ONLY,
        role_kind="mixed",
    )
    assert result.gate_triggered == "Балл срезан: формат-гейт"
    assert result.recommendation == "skip"


def test_hr_override_beats_both_pieces_of_evidence():
    """Слова HR перекрывают и JD, и вердикт модели (JS-8.1)."""
    for override in ("remote", "hybrid"):
        verdict = evaluate_format("blocker", _OFFICE_JD, _REMOTE_ONLY, override)
        assert verdict.gate is False
        assert verdict.delta == 0


def test_empty_schedule_keeps_format_gate_silent():
    """Резюме без допустимых форматов — не повод навязывать remote-only."""
    assert evaluate_format("blocker", _OFFICE_JD, _EMPTY_SCHEDULE) == evaluate_format(
        "ok", _NEUTRAL_JD, _EMPTY_SCHEDULE
    )
    gated = _score(format_level="blocker")
    assert detect_gates(gated, _OFFICE_JD, format_prefs=_EMPTY_SCHEDULE) is None


def test_office_only_jd_is_silent_when_candidate_allows_office():
    verdict = evaluate_format("ok", _OFFICE_JD, _OFFICE_OK)
    assert verdict.gate is False
    assert verdict.delta == 0
