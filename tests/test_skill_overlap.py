"""Этап 4 §4.3 (plans/scoring_precision_2026_08_17.md): оверлап навыков как под-сигнал.

`vacancy_skill_requirements` уже считается фоном и раньше в скор не входил. Ноль новых
LLM-вызовов: если требования по вакансии уже посчитаны - берём, если нет - компонента
нейтральна (не штраф за отсутствие данных).
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import SkillRequirement
from core.domains.opportunities.score_breakdown import (
    role_content_fraction,
    skill_overlap_fraction,
)


def _req(skill: str, importance: str = "required") -> SkillRequirement:
    return SkillRequirement(skill=skill, importance=importance)


def test_no_requirements_data_is_neutral_none():
    """Требований по вакансии ещё нет (фон не успел) → None, не 0."""
    assert skill_overlap_fraction(None, key_skills=["Python"], niches=["MLOps"]) is None


def test_empty_required_list_is_neutral_none():
    """Есть только preferred-навыки — сверять нечего, тоже нейтрально, не штраф."""
    required = [_req("Docker", importance="preferred")]
    assert skill_overlap_fraction(required, key_skills=[], niches=[]) is None


def test_full_coverage_by_key_skills():
    required = [_req("Python"), _req("Kubernetes")]
    overlap = skill_overlap_fraction(required, key_skills=["Python", "k8s"], niches=[])
    assert overlap == 1.0


def test_partial_coverage_counts_only_matched():
    required = [_req("Python"), _req("Go"), _req("Rust")]
    overlap = skill_overlap_fraction(required, key_skills=["Python"], niches=[])
    assert overlap == 1 / 3


def test_preferred_skills_do_not_count_toward_overlap():
    required = [_req("Python"), _req("Docker", importance="preferred")]
    # Docker покрыт, но он preferred - не в знаменателе; Python не покрыт.
    overlap = skill_overlap_fraction(required, key_skills=["Docker"], niches=[])
    assert overlap == 0.0


def test_match_via_skill_canon_alias():
    required = [_req("k8s")]
    assert skill_overlap_fraction(required, key_skills=["Kubernetes"], niches=[]) == 1.0


def test_niche_match_gives_full_credit_when_single_niche():
    required = [_req("MLOps")]
    assert skill_overlap_fraction(required, key_skills=[], niches=["MLOps"]) == 1.0


def test_top_priority_niche_weighs_more_than_last():
    """Этап 4 §4.4: совпадение с приоритетом №1 весит больше, чем с приоритетом №6."""
    niches = ["Top Niche", "Mid Niche", "Last Niche"]
    top_match = skill_overlap_fraction([_req("Top Niche")], key_skills=[], niches=niches)
    last_match = skill_overlap_fraction([_req("Last Niche")], key_skills=[], niches=niches)
    assert top_match is not None and last_match is not None
    assert top_match > last_match
    assert top_match == 1.0


def test_key_skills_always_full_weight_regardless_of_niche_rank():
    required = [_req("Python")]
    overlap = skill_overlap_fraction(
        required, key_skills=["Python"], niches=["Irrelevant Niche 1", "Irrelevant Niche 2"]
    )
    assert overlap == 1.0


def test_role_content_fraction_pure_llm_when_overlap_missing():
    assert role_content_fraction(80, None) == pytest.approx(0.8)


def test_role_content_fraction_blends_llm_and_overlap():
    # 0.65 * 0.8 + 0.35 * 1.0
    assert role_content_fraction(80, 1.0) == pytest.approx(0.87)


def test_role_content_fraction_low_overlap_pulls_score_down():
    blended = role_content_fraction(80, 0.0)
    assert blended < 0.8
    assert blended == 0.65 * 0.8
