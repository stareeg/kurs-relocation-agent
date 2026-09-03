"""Качество выхода strengthen/ATS — анти-косметика."""

from __future__ import annotations

from core.domains.profile.model import ResumeData, SearchCriteria
from core.domains.profile.strengthen_quality import (
    COSMETIC_SIMILARITY_THRESHOLD,
    format_enhancement_directive,
    is_substantive_enhancement,
    token_jaccard_similarity,
)


def test_cosmetic_paraphrase_detected() -> None:
    original = "Разрабатывал backend-сервисы на Python для внутренних отчётов."
    paraphrase = "Разрабатывал backend-сервисы на Python для внутренних отчётов компании."
    assert token_jaccard_similarity(original, paraphrase) >= COSMETIC_SIMILARITY_THRESHOLD
    assert not is_substantive_enhancement(original, paraphrase)


def test_substantive_enhancement_with_new_content() -> None:
    original = "Писал SQL-запросы для отчётов."
    enhanced = (
        "- Спроектировал витрины в Greenplum для финансовых отчётов, "
        "сократил time-to-market с 2 недель до 4 дней\n"
        "- Вёл ревью SQL команды из 4 человек, внедрил lint в CI"
    )
    assert is_substantive_enhancement(original, enhanced)


def test_enhancement_directive_includes_grade_and_niches() -> None:
    data = ResumeData(
        position={"title": "Lead LLM Engineer", "grade": ["Senior", "Lead"]},
        search_criteria=SearchCriteria(
            role_kind="hands_on",
            market_segment="FinTech",
            niches=["LLM/RAG"],
        ),
    )
    block = format_enhancement_directive(data)
    assert "Senior" in block
    assert "LLM/RAG" in block
    assert "не пересказ" in block.casefold()
