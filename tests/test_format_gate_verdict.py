"""Поведение формат-гейта: вердикт модели, а не только регекс по тексту JD."""

from __future__ import annotations

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.rules import CandidateFormatPrefs, detect_gates

_REMOTE_ONLY = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
# Ни одного маркера офиса: единственная улика — вердикт модели.
_QUIET_JD = "senior ml engineer, интересные задачи, сильная команда"


def _score(format_level: str) -> ScoreResult:
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


def test_format_gate_reads_model_verdict_not_only_text():
    """Без маркера офиса в тексте гейт срабатывает по `blocker` и молчит по `ok`."""
    blocker = detect_gates(_score("blocker"), _QUIET_JD, format_prefs=_REMOTE_ONLY)
    ok = detect_gates(_score("ok"), _QUIET_JD, format_prefs=_REMOTE_ONLY)
    assert blocker == "Балл срезан: формат-гейт"
    assert ok is None
