"""Тесты чистого модуля дедупликации — canonical_tokens, jaccard, find_duplicate."""

from __future__ import annotations

from dataclasses import dataclass

from core.domains.opportunities.dedup import (
    DUP_THRESHOLD,
    canonical_tokens,
    find_duplicate,
    jaccard,
    strip_html,
    tokens_array,
)


@dataclass
class _FakeCandidate:
    id: int | None
    vacancy_text: str


def test_strip_html_removes_tags():
    assert strip_html("<p>hello</p>") == " hello "
    assert strip_html("<br/><span>text</span>") == "  text "
    assert strip_html("no tags") == "no tags"


def test_canonical_tokens_normal():
    text = "Senior Python Developer: Удалённая работа, зарплата от 300 000 ₽"
    tokens = canonical_tokens(text)
    assert "senior" in tokens
    assert "python" in tokens
    assert "developer" in tokens
    # Бойлерплейт-метки удалены
    assert "зарплата" not in tokens
    # Пунктуация снята
    assert "300" in tokens
    assert "000" in tokens
    # Слова из бойлерплейт-меток без них — остаются
    assert "работа" in tokens
    assert "удалённая" in tokens


def test_canonical_tokens_strips_html_then_tokenizes():
    text = "<div>Senior <b>Python</b> Developer</div>"
    tokens = canonical_tokens(text)
    assert tokens >= {"senior", "python", "developer"}


def test_canonical_tokens_empty_text_returns_empty():
    assert canonical_tokens("") == frozenset()
    assert canonical_tokens("   ") == frozenset()


def test_jaccard_identical_sets_returns_one():
    assert jaccard({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint_sets_returns_zero():
    assert jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial_overlap():
    # intersection=2, union=4 → 0.5
    score = jaccard({"a", "b", "c"}, {"a", "b", "d"})
    assert score == 0.5


def test_jaccard_both_empty_returns_zero():
    assert jaccard([], []) == 0.0


def test_find_duplicate_above_threshold():
    """Кандидат с Jaccard > порога — найден. Тексты почти идентичны, порог 0.3."""
    cand = _FakeCandidate(
        id=1,
        vacancy_text=(
            "ищем senior python разработчика в команду высоконагруженных сервисов. "
            "требуется опыт docker kubernetes postgresql от 5 лет. "
            "удалённая работа, зарплата от 350 до 500 тысяч."
        ),
    )
    dup = find_duplicate(
        "ищем senior python разработчика в команду высоконагруженных сервисов. "
        "требуется опыт docker kubernetes postgresql от 4 лет. "
        "удалённая работа, зарплата от 350 до 500 тысяч рублей.",
        [cand],
        threshold=0.3,
    )
    assert dup is not None
    assert dup.id == 1


def test_find_duplicate_below_threshold_returns_none():
    """Jaccard ниже порога — None."""
    cand = _FakeCandidate(id=1, vacancy_text="Junior Frontend React, офис, Москва")
    dup = find_duplicate(
        "Senior Backend Go, удалённо",
        [cand],
        threshold=0.5,
    )
    assert dup is None


def test_find_duplicate_empty_incoming_returns_none():
    cand = _FakeCandidate(id=1, vacancy_text="some text")
    assert find_duplicate("   ", [cand]) is None


def test_find_duplicate_no_candidates_returns_none():
    assert find_duplicate("some text", []) is None


def test_find_duplicate_default_threshold_is_0_9():
    assert DUP_THRESHOLD == 0.9


def test_tokens_array_returns_sorted_list():
    tokens = tokens_array("Python Senior Developer")
    assert isinstance(tokens, list)
    assert tokens == sorted(tokens)
    assert "developer" in tokens
    assert "python" in tokens
    assert "senior" in tokens


def test_boilerplate_labels_removed():
    """Метки 'компания', 'навыки', 'зарплата' и т.п. удаляются из токенов."""
    text = "Компания: Яндекс. Навыки: Python, Go. Зарплата: высокая"
    tokens = canonical_tokens(text)
    assert "компания" not in tokens
    assert "навыки" not in tokens
    assert "зарплата" not in tokens
    assert "яндекс" in tokens
    assert "python" in tokens
    assert "go" in tokens
    assert "высокая" in tokens