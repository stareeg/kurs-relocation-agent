"""Этап 4 §4.2 (plans/scoring_precision_2026_08_17.md): канон написаний `matched_niche`.

На проде MLOps/LLMOps встречалось в 5 написаниях (189 упоминаний), RAG - в 3, AI Safety - в 2
(§1.7 плана). Без схлопывания аналитика по нишам не считается.
"""

from __future__ import annotations

from pathlib import Path

from core.domains.opportunities.niche_canon import (
    NICHE_CANON_PATH,
    canonical_niche_name,
    canonicalize_niches,
)


def test_niche_canon_file_exists():
    """Синк-тест на существование словаря (Этап 4 §4.2 плана) — путь читается от CWD=корень репо."""
    assert Path(NICHE_CANON_PATH).exists(), f"не найден словарь канона ниш: {NICHE_CANON_PATH}"


def test_mlops_llmops_spellings_converge_to_one_canon():
    assert canonical_niche_name("mlops/llmops") == "MLOps/LLMOps"
    assert canonical_niche_name("MLOps и LLMOps") == "MLOps/LLMOps"
    assert canonical_niche_name("LLMOps и MLOps") == "MLOps/LLMOps"
    assert canonical_niche_name("llm-инфраструктура") == "MLOps/LLMOps"


def test_ampersand_and_и_spellings_are_equivalent():
    assert canonical_niche_name("AI Safety & Guardrails") == "AI Safety & Guardrails"
    assert canonical_niche_name("AI Safety и Guardrails") == "AI Safety & Guardrails"
    assert canonical_niche_name("LLM & RAG") == "LLM & RAG"
    assert canonical_niche_name("LLM и RAG") == "LLM & RAG"


def test_rag_spellings_converge_to_one_canon():
    assert canonical_niche_name("RAG") == "LLM & RAG"
    assert canonical_niche_name("RAG и GraphRAG") == "LLM & RAG"


def test_unknown_niche_passes_through_unchanged():
    # Ниша кандидата другой специальности (не AI/ML) - канон её не знает и не трогает.
    assert canonical_niche_name("Agile Delivery") == "Agile Delivery"
    assert canonical_niche_name("  Стейкхолдер-менеджмент  ") == "Стейкхолдер-менеджмент"


def test_canonicalize_niches_dedupes_after_canon():
    result = canonicalize_niches(["mlops/llmops", "mlops и llmops", "RAG"])
    assert result == ["MLOps/LLMOps", "LLM & RAG"]


def test_canonicalize_niches_keeps_first_appearance_order():
    result = canonicalize_niches(["RAG", "Agentic AI", "mlops"])
    assert result == ["LLM & RAG", "Agentic AI", "MLOps/LLMOps"]


def test_canonicalize_niches_strips_blanks():
    assert canonicalize_niches(["", "  ", "RAG"]) == ["LLM & RAG"]
