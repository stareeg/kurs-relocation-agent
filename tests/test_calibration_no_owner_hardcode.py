"""Калибровка без owner-хардкода: предпочтения только из резюме / явных правил."""

from __future__ import annotations

from pathlib import Path

from core.platform.repo.settings import DEFAULT_COMPANY_ADJUSTMENTS
from core.domains.opportunities.rules import (
    CandidateFormatPrefs,
    apply_calibration,
    compute_adjustments,
    rules_from_search_lists,
)
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.score_breakdown import compute_score_breakdown

_OFFICE_OK = CandidateFormatPrefs(
    allows_office=True,
    allows_hybrid=True,
    allows_remote=False,
    travel_is_dealbreaker=False,
)
_REMOTE_ONLY = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=False,
)
_EMPTY_SCHEDULE = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=False,
    travel_is_dealbreaker=False,
)
_TRAVEL_DB = CandidateFormatPrefs(
    allows_office=False,
    allows_hybrid=False,
    allows_remote=True,
    travel_is_dealbreaker=True,
)

_OFFICE_JD = (
    "Формат работы: офис 5/5 на месте, только офис.\n"
    "Компания: ПАО Сбербанк. Senior Project Manager.\n"
    "Зарплата от 450 000. Командировки в Ереван."
)
_MTS_JD = "Компания МТС, product media. Полная удалёнка. Вилка от 500 000."


def _score(*, overall: int = 80, format_level: str = "ok") -> ScoreResult:
    return ScoreResult(
        overall_score=overall,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level=format_level, reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500000", note=""),
        role_content_match=RoleContentMatch(score=80, matched_niche=["Project management"], reasoning="r"),
        burnout_risk=BurnoutRisk(level="medium", reasoning="r"),
        company_type="bank",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )


def test_default_company_adjustments_empty():
    assert DEFAULT_COMPANY_ADJUSTMENTS == []


def test_no_sber_vk_yandex_penalty_without_rules():
    """Раньше хардкод резал Сбер/VK/Яндекс даже у «чистого» друга."""
    adj = compute_adjustments(
        _score(),
        _OFFICE_JD.lower(),
        company_adjustments=[],
        company="ПАО Сбербанк",
        list_rules=[],
        format_prefs=_REMOTE_ONLY,
    )
    reasons = " ".join(a.reason.casefold() for a in adj)
    assert "сбер" not in reasons
    assert "vk" not in reasons
    assert "яндекс" not in reasons
    assert "мтс" not in reasons
    assert "400k" not in reasons
    assert "phd" not in reasons
    assert "burnout" not in reasons


def test_no_mts_or_salary400k_bonus():
    adj = compute_adjustments(
        _score(),
        _MTS_JD.lower(),
        company_adjustments=[],
        list_rules=[],
        format_prefs=_REMOTE_ONLY,
    )
    assert adj == [] or all(a.reason != "МТС / крупный product media" for a in adj)
    assert all("400k" not in a.reason for a in adj)
    assert all(a.delta <= 0 for a in adj)  # без owner-плюсов


def test_office_gate_skipped_when_candidate_allows_office():
    """PM/друг с офисом в резюме не получает remote-only гейт."""
    result = apply_calibration(
        _score(overall=80),
        _OFFICE_JD,
        company_adjustments=[],
        list_rules=[],
        format_prefs=_OFFICE_OK,
        role_kind="unknown",
    )
    assert result.gate_triggered is None
    assert result.recommendation != "skip"
    # База — детерминированный breakdown по весам, не сырой overall_score из фикстуры (apply_calibration
    # игнорирует его нарочно, см. core/domains/opportunities/rules.py); без списков/ручных правил деталей нет,
    # так что итог равен сумме breakdown без каких-либо калибровочных дельт.
    assert result.overall_score == sum(
        compute_score_breakdown(_score(overall=80), role_kind="unknown").values()
    )


def test_office_gate_when_remote_only_candidate():
    """Гейт формата — по вердикту модели (Этап 1 §1.2): офис-only в JD + `blocker`."""
    result = apply_calibration(
        _score(overall=80, format_level="blocker"),
        _OFFICE_JD,
        company_adjustments=[],
        list_rules=[],
        format_prefs=_REMOTE_ONLY,
        role_kind="unknown",
    )
    assert result.gate_triggered is not None
    assert "формат" in (result.gate_triggered or "").casefold()
    assert result.recommendation == "skip"


def test_empty_schedule_does_not_force_remote_gate():
    result = apply_calibration(
        _score(overall=80),
        _OFFICE_JD,
        company_adjustments=[],
        list_rules=[],
        format_prefs=_EMPTY_SCHEDULE,
        role_kind="unknown",
    )
    assert result.gate_triggered is None
    assert result.overall_score == sum(
        compute_score_breakdown(_score(overall=80), role_kind="unknown").values()
    )


def test_travel_penalty_only_with_dealbreaker():
    without = compute_adjustments(
        _score(),
        _OFFICE_JD.lower(),
        company_adjustments=[],
        format_prefs=_REMOTE_ONLY,
    )
    with_db = compute_adjustments(
        _score(),
        _OFFICE_JD.lower(),
        company_adjustments=[],
        format_prefs=_TRAVEL_DB,
    )
    assert not any("командиров" in a.reason for a in without)
    assert any("командиров" in a.reason for a in with_db)


def test_pm_style_avoid_list_still_works():
    list_rules = rules_from_search_lists([], ["Сбербанк"])
    result = apply_calibration(
        _score(overall=90),
        "полная удалёнка, Project Manager",
        company_adjustments=[],
        company="ПАО Сбербанк",
        list_rules=list_rules,
        format_prefs=_REMOTE_ONLY,
        role_kind="unknown",
    )
    assert result.recommendation == "skip"
    assert "избегать" in (result.gate_triggered or "")


def test_none_company_adjustments_same_as_empty():
    """None больше не подтягивает legacy hardcode."""
    a = compute_adjustments(
        _score(),
        "работа в сбере vk yandex мтс miccai",
        company_adjustments=None,
        format_prefs=_REMOTE_ONLY,
    )
    b = compute_adjustments(
        _score(),
        "работа в сбере vk yandex мтс miccai",
        company_adjustments=[],
        format_prefs=_REMOTE_ONLY,
    )
    assert a == b
    assert a == []


# --- Этап 8 §8.4 (D13): модули скоринга без топонимов/персональных строк владельца ---
# `scorer.py::_REMOTE_KEYWORDS` содержал "из минска"/"минск"/"из польш"/"польш" — личная
# география владельца, зашитая в фильтр remote-упоминаний. Скан по исходникам, а не только
# regression-тест на удалённые строки: ловит и будущий рецидив в любом другом месте этих
# двух модулей, не только в конкретной константе.

_SCORING_MODULES = (
    Path(__file__).resolve().parent.parent / "core" / "domains" / "opportunities" / "scorer.py",
    Path(__file__).resolve().parent.parent / "core" / "domains" / "opportunities" / "rules.py",
    Path(__file__).resolve().parent.parent / "core" / "domains" / "opportunities" / "track_classify.py",
    Path(__file__).resolve().parent.parent / "core" / "domains" / "opportunities" / "work_terms.py",
    Path(__file__).resolve().parent.parent
    / "core"
    / "domains"
    / "opportunities"
    / "score_breakdown.py",
)

# Личная география владельца (D13) — не должна встречаться в коде скоринга ни в каком виде.
_BANNED_TOPONYMS = ("минск", "польш", "беларус", "belarus", "warsaw", "варшав")


def test_scoring_modules_have_no_owner_toponyms():
    for path in _SCORING_MODULES:
        text = path.read_text(encoding="utf-8").casefold()
        for needle in _BANNED_TOPONYMS:
            assert needle not in text, f"owner-топоним «{needle}» найден в {path.name}"


def test_remote_keywords_no_longer_hardcode_owner_geo():
    """Регресс на сам инцидент: раньше `_REMOTE_KEYWORDS` резал "из минска" и "из польш"."""
    from core.domains.opportunities.scorer import _REMOTE_KEYWORDS

    for needle in ("минск", "польш"):
        assert needle not in _REMOTE_KEYWORDS
