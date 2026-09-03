"""Шаг 24: термины рынка из корпуса вместо зашитого CONCEPTS."""

from __future__ import annotations

from core.domains.profile.corpus_terms import extract_corpus_terms
from core.domains.profile.gap import compile_concepts


def _pm_vacancy(i: int) -> str:
    """Синтетическая PM-вакансия: ключевые термины + HR-шум."""
    return (
        f"Вакансия Project Manager #{i}. Компания ищет специалиста в команду. "
        "Обязанности: управление проектами, контроль сроков и коммуникация со стейкхолдерами. "
        "Нужен опыт работы, знание задач и процессов. "
        "Стейкхолдеры ожидают прозрачный статус: сроки и риски на виду. "
        "Требования: опыт, работа в компании, задачи команды."
    )


def test_extract_empty_corpus_returns_empty() -> None:
    assert extract_corpus_terms([]) == []
    assert extract_corpus_terms(["короткий текст"] * 10) == []


def test_extract_pm_corpus_keeps_domain_terms_drops_stopwords() -> None:
    corpus = [_pm_vacancy(i) for i in range(20)]
    terms = extract_corpus_terms(corpus)
    names = {t.name for t in terms}

    assert "управление проектами" in names
    assert "стейкхолдеры" in names
    assert "сроки" in names

    for noise in ("команда", "опыт", "работа", "компания", "задачи", "требования", "вакансия"):
        assert noise not in names

    assert all(0.10 <= t.df <= 1.0 for t in terms)
    assert all(t.pattern.search(_pm_vacancy(0)) for t in terms if t.name in {
        "управление проектами", "стейкхолдеры", "сроки"
    })


def test_compile_concepts_ignores_corpus_stays_empty_for_non_it() -> None:
    """A-02: corpus_terms больше не подмешивается — непустой корпус не поднимает non-IT сегмент."""
    corpus = [_pm_vacancy(i) for i in range(20)]
    patterns = compile_concepts(corpus, market_segment="Медиа / Продакшн")
    assert patterns == {}


def test_compile_concepts_non_it_without_corpus_is_empty() -> None:
    patterns = compile_concepts([], market_segment="Медиа / Продакшн")
    assert patterns == {}


def test_compile_concepts_it_fallback_to_builtins() -> None:
    patterns = compile_concepts([], market_segment="IT")
    assert "Python" in patterns
    assert "RAG" in patterns


def test_compile_concepts_ignores_corpus_uses_builtins_for_it() -> None:
    """A-02: непустой корпус на IT-сегменте больше не вытесняет CONCEPTS корпусными n-граммами."""
    corpus = [_pm_vacancy(i) for i in range(20)]
    patterns = compile_concepts(corpus, market_segment="IT")
    assert "Python" in patterns
    assert "управление проектами" not in patterns


def test_compile_concepts_empty_segment_allows_builtins() -> None:
    patterns = compile_concepts([], market_segment="")
    assert "Python" in patterns
