"""Смоук: Project Manager (офис/гибрид) — промпт и калибровка без Lead LLM / remote-only хардкода."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from core.config import get_settings
from core.domains.profile.model import ResumeData
from core.domains.opportunities.rules import (
    CandidateFormatPrefs,
    apply_calibration,
    format_prefs_from_profile,
)
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.prompt import (
    build_system_prompt_text,
    clear_resume_cache,
    load_candidate_identity,
    load_candidate_min_salary,
    load_candidate_specialization,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "resume_smoke_pm.json"

FORBIDDEN = (
    "Lead LLM Engineer",
    "ex-Сбер",
    "GraphRAG",
    "agentic",
    "450 000",  # зарплата PM в фикстуре 250k — owner-порог не должен торчать
)


@pytest.fixture
def pm_resume_env(tmp_path, monkeypatch):
    dest = tmp_path / "resume_data.json"
    shutil.copy(FIXTURE, dest)
    monkeypatch.setenv("RESUME_DATA_PATH", str(dest))
    get_settings.cache_clear()
    clear_resume_cache()
    yield dest
    get_settings.cache_clear()


def test_pm_fixture_category_and_office_schedule():
    data = ResumeData.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    assert "Project Management" in data.position.categories
    assert data.position.title == "Project Manager"
    assert "Офис" in data.position.schedule
    assert data.position.salary_min == 250_000
    assert data.position.salary_basis == "На руки"
    assert data.search_criteria.role_kind == "Управляю людьми"
    assert data.search_criteria.market_segment == "IT"


def test_pm_prompts_and_salary_from_resume(pm_resume_env):
    identity = load_candidate_identity()
    specialization = load_candidate_specialization()
    prompt = build_system_prompt_text()

    assert "Project Manager" in identity or "Project Manager" in specialization
    assert "Project Manager" in prompt
    assert "Agile delivery" in prompt
    assert load_candidate_min_salary() == 250_000

    lowered = prompt.lower()
    for needle in FORBIDDEN:
        assert needle.lower() not in lowered, f"в промпте PM найден «{needle}»"


def test_pm_format_prefs_allow_office(pm_resume_env):
    from core.domains.profile.profile import load_search_profile

    prefs = format_prefs_from_profile(load_search_profile())
    assert prefs.allows_office
    assert prefs.allows_hybrid
    assert prefs.travel_is_dealbreaker


def test_pm_office_vacancy_not_hard_gated(pm_resume_env):
    from core.domains.profile.profile import load_search_profile

    profile = load_search_profile()
    prefs = format_prefs_from_profile(profile)
    score = ScoreResult(
        overall_score=75,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="офис ок"),
        grade_match=GradeMatch(level="match", reasoning="senior"),
        salary=SalaryInfo(meets_min=True, value_or_range="280000", note=""),
        role_content_match=RoleContentMatch(
            score=70, matched_niche=["Agile delivery"], reasoning="pm"
        ),
        burnout_risk=BurnoutRisk(level="low", reasoning="ok"),
        company_type="product",
        pros=["delivery"],
        cons=["нет вилки в тексте"],
        red_flags=[],
        one_line_verdict="ок",
    )
    result = apply_calibration(
        score,
        "Формат работы: офис 5/5 на месте, только офис.\nИщем Project Manager.",
        company_adjustments=[],
        list_rules=[],
        format_prefs=prefs,
        role_kind=profile.role_kind,
    )
    assert result.gate_triggered is None
    assert result.recommendation != "skip"

    # Контроль: тот же JD для remote-only — гейт есть, но по вердикту модели, а не по регексу
    # (Этап 1 §1.2: одного «офис-only» в тексте на дилбрейкер не хватает).
    remote_only = CandidateFormatPrefs(
        allows_office=False,
        allows_hybrid=False,
        allows_remote=True,
        travel_is_dealbreaker=False,
    )
    office_jd = "Формат работы: офис 5/5 на месте, только офис.\nИщем Project Manager."
    gated = apply_calibration(
        score.model_copy(
            update={"remote_abroad_compat": RemoteAbroadCompat(level="blocker", reasoning="офис")}
        ),
        office_jd,
        company_adjustments=[],
        list_rules=[],
        format_prefs=remote_only,
        role_kind=profile.role_kind,
    )
    assert gated.recommendation == "skip"

    # А при вердикте модели «формат подходит» тот же текст даёт мягкий минус, не skip.
    soft = apply_calibration(
        score,
        office_jd,
        company_adjustments=[],
        list_rules=[],
        format_prefs=remote_only,
        role_kind=profile.role_kind,
    )
    assert soft.gate_triggered is None
    assert any("расхождение" in a.reason for a in soft.adjustments)


def test_pm_system_prompt_no_owner_management_bias(pm_resume_env):
    """Шаг 11: критерий «Управление» без owner-предпочтения «код руками»."""
    prompt = build_system_prompt_text()
    lowered = prompt.casefold()
    for needle in (
        "важен код руками",
        "hands-on",
        "чистый менеджмент — минус",
        "чистый менеджмент - минус",
    ):
        assert needle.casefold() not in lowered, f"в system-промпте найден owner-bias «{needle}»"


def test_pm_media_company_type_neutral_fraction():
    """Шаг 14: media валидируется и даёт долю 0.55 (не outsource 0.25)."""
    from core.domains.opportunities.score_breakdown import COMPANY_WEIGHT, compute_score_breakdown

    media = ScoreResult(
        overall_score=70,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="250000", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="high", reasoning="r"),
        company_type="media",
        pros=["ок"],
        cons=["ок"],
        red_flags=[],
        one_line_verdict="ок",
    )
    outsource = media.model_copy(update={"company_type": "outsource"})
    media_pts = compute_score_breakdown(media, role_kind="management")["company"]
    out_pts = compute_score_breakdown(outsource, role_kind="management")["company"]
    assert media_pts == round(COMPANY_WEIGHT * 0.55)
    assert out_pts == round(COMPANY_WEIGHT * 0.25)
    assert media_pts > out_pts


def test_pm_situation_goal_from_resume(pm_resume_env):
    """Шаг 28: ЦЕЛЬ в situation user-промпте из резюме PM, без owner-хардкода."""
    from core.domains.market.situation import SituationFacts, build_situation_user_prompt
    from core.domains.profile.profile import load_search_profile
    from core.domains.profile.structured_store import read_resume_data_from_file

    profile = load_search_profile()
    companies = list(read_resume_data_from_file().search_criteria.target_companies or [])
    prompt = build_situation_user_prompt(
        SituationFacts(horizon_days=60),
        profile=profile,
        target_companies=companies,
    )

    assert "Project Manager" in prompt
    assert "250 000" in prompt
    assert "Тинькофф" in prompt or "Авито" in prompt
    lowered = prompt.casefold()
    for needle in ("бигтех", "450 000", "полной удалёнке"):
        assert needle.casefold() not in lowered, f"в situation user-промпте найден «{needle}»"


def test_pm_middle_vacancy_strong_apply(pm_resume_env):
    """Шаг 16: Middle-PM под профиль «Управляю людьми» → strong_apply (потолок 74 снят)."""
    from core.domains.profile.profile import load_search_profile

    profile = load_search_profile()
    assert profile.role_kind == "management"
    assert profile.salary_basis == "net"
    assert profile.market_segment == "IT"

    score = ScoreResult(
        overall_score=70,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="гибрид/офис"),
        grade_match=GradeMatch(level="match", reasoning="middle pm"),
        salary=SalaryInfo(meets_min=True, value_or_range="260000", note=""),
        role_content_match=RoleContentMatch(
            score=85, matched_niche=["Agile delivery"], reasoning="pm delivery"
        ),
        burnout_risk=BurnoutRisk(level="high", reasoning="управление людьми"),
        company_type="media",
        pros=["delivery", "грейд"],
        cons=["медиа, не продукт"],
        red_flags=[],
        one_line_verdict="сильный match для PM",
    )
    prefs = format_prefs_from_profile(profile)
    result = apply_calibration(
        score,
        "Project Manager (Middle). Гибрид Москва. Медиа-продакшн.\n"
        "Ведёте кросс-функциональную команду, Jira, roadmap.",
        company_adjustments=[],
        list_rules=[],
        format_prefs=prefs,
        role_kind=profile.role_kind,
    )
    assert result.gate_triggered is None
    assert result.overall_score >= 80
    assert result.recommendation == "strong_apply"


def test_pm_international_derivation_does_not_invent_ready():
    data = ResumeData.model_validate(json.loads(FIXTURE.read_text(encoding="utf-8")))
    from core.domains.profile.international import derive_international_readiness

    ready = derive_international_readiness(data)
    assert ready.readiness == "unknown"
    data.search_criteria.market_scope = "Международный"
    intl = derive_international_readiness(data)
    assert intl.readiness != "ready"
    assert intl.home_timezone == "Europe/Moscow"
    assert intl.english_level == ""
