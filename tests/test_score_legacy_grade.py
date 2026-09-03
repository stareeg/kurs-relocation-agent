"""Легаси grade_match.level в jsonb и фолбэки без скоринга."""

from __future__ import annotations

from core.domains.market.salary_benchmark import _job_grade_bucket
from core.domains.preparation.interview.records import _fallback_score
from core.domains.opportunities.models import GradeMatch, ScoreResult
from core.domains.opportunities.rules import CandidateFormatPrefs, detect_gates
from core.domains.opportunities.score_breakdown import compute_score_breakdown
from core.domains.preparation.screening.questions import _parse_groups

# Пустой schedule — гейты/минусы формата молчат; в этих тестах проверяется только грейд-гейт.
_EMPTY_SCHEDULE = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=False,
    travel_is_dealbreaker=False,
)


def _minimal_score(**overrides: object) -> dict:
    base = {
        "overall_score": 50,
        "recommendation": "maybe",
        "remote_abroad_compat": {"level": "ok", "reasoning": "x"},
        "grade_match": {"level": "match", "reasoning": "x"},
        "salary": {
            "meets_min": False,
            "value_or_range": "",
            "estimated_range": "",
            "note": "",
        },
        "role_content_match": {"score": 50, "matched_niche": [], "reasoning": ""},
        "burnout_risk": {"level": "medium", "reasoning": "x"},
        "company_type": "unknown",
        "pros": ["a"],
        "cons": ["b"],
        "red_flags": [],
        "one_line_verdict": "ok",
    }
    base.update(overrides)
    return base


def test_grade_match_coerces_legacy_mid() -> None:
    gm = GradeMatch.model_validate({"level": "mid", "reasoning": "старый jsonb"})
    assert gm.level == "slightly_below"


def test_legacy_off_profile_without_kind_behaves_as_other_profession() -> None:
    """Этап 1 §1.3: сохранённый score без `off_profile_kind` гейтится как раньше."""
    gm = GradeMatch.model_validate({"level": "off_profile", "reasoning": "старый jsonb"})
    assert gm.off_profile_kind == ""
    assert gm.is_role_shift is False

    score = ScoreResult.model_validate(
        _minimal_score(grade_match={"level": "off_profile", "reasoning": "старый jsonb"})
    )
    assert (
        detect_gates(score, "полная удалёнка, senior позиция", format_prefs=_EMPTY_SCHEDULE)
        == "Балл срезан: грейд-гейт"
    )
    assert compute_score_breakdown(score, role_kind="mixed")["grade_match"] == 0


def test_score_result_loads_legacy_senior_plus() -> None:
    score = ScoreResult.model_validate(
        _minimal_score(grade_match={"level": "senior_plus", "reasoning": "legacy"})
    )
    assert score.grade_match.level == "match"


def test_fallback_score_uses_relative_grade() -> None:
    score = _fallback_score("100k")
    assert score.grade_match.level == "match"


def test_job_grade_bucket_maps_relative_and_legacy() -> None:
    assert _job_grade_bucket({"grade_match": {"level": "match"}}) == "senior_plus"
    assert _job_grade_bucket({"grade_match": {"level": "slightly_below"}}) == "mid"
    assert _job_grade_bucket({"grade_match": {"level": "mid"}}) == "mid"
    assert _job_grade_bucket({"grade_match": {"level": "off_profile"}}) is None


def test_parse_groups_recovers_probe_as_question() -> None:
    groups = _parse_groups(
        [
            {
                "title": "Стек",
                "hook": "Multica",
                "questions": [
                    {
                        "probe": "Это внутренние фреймворки или open-source?",
                        "expect": "Если внутренние - обучают на месте",
                    }
                ],
            }
        ]
    )
    assert len(groups) == 1
    assert groups[0].questions[0].question.startswith("Это внутренние")
