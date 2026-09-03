"""Дедупликация вакансий между площадками: одна логическая вакансия — несколько ссылок.

Кросс-площадочный поиск дублей (hh / getmatch / habr / telegram): тексты с разных площадок
отличаются бойлерплейтом и HTML-обёрткой, поэтому метрика — Jaccard по токенам слов (устойчивее
trigram-сходства), а перед сравнением текст канонизируется (снимаем теги, lowercase, пунктуацию,
схлопываем пробелы, отрезаем служебные метки «Навыки: …» / «Квалификация: …»).

Модуль чистый (без I/O): юнит-тестируется как `score_breakdown.py`. Префильтр кандидатов по
`jobs.text_tokens` живёт в `jobs.py` (там SQL), здесь — только точное сравнение в Python.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Protocol, TypeVar, runtime_checkable

# Порог совпадения: >0.9 по Jaccard — считаем одну и ту же вакансию на разных площадках.
DUP_THRESHOLD = 0.9

_TAG_RE = re.compile(r"<[^>]+>")

# Метки структурных блоков, которые инжектит парсер Хабр (и аналогичный бойлерплейт других
# площадок): сами слова-метки не несут смысла вакансии, но завышали бы сходство текстов,
# выровненных под один парсер. Значения после метки (навыки/грейд) остаются токенами.
_BOILERPLATE_LABELS = frozenset(
    {
        "компания",
        "зарплата",
        "локация",
        "навыки",
        "квалификация",
        "специализации",
        "опыт",
    }
)


def strip_html(text: str) -> str:
    """Снять HTML-теги, заменив на пробел (чтобы `a<b` не склеилось в `ab`)."""
    return _TAG_RE.sub(" ", text)


def _normalize(text: str) -> str:
    """Нижний регистр + нормализация Unicode + расклейка HTML-сущностей-пробелов."""
    text = text.lower()
    # NFKC расклеивает ligatures/full-width, но может слить символы — до lower, чтобы «Т» и «т»
    # не различались; заменяем неразрывные пробелы и прочие пробельные на обычный пробел ниже.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", " ").replace("\u200c", " ").replace("\u200d", " ")
    return text


_TOKEN_RE = re.compile(r"\b[\wа-яё]+\b", re.UNICODE)


def canonical_tokens(text: str) -> frozenset[str]:
    """Канонические токены текста вакансии для Jaccard-сравнения.

    Снимаем HTML, lowercase, выкидываем пунктуацию, схлопываем пробелы, отрезаем служебные
    метки структурных блоков. Возвращаем frozenset слов (порядок/повторы неважны).
    """
    if not text:
        return frozenset()
    plain = strip_html(text)
    plain = _normalize(plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return frozenset()
    tokens = {m.group(0) for m in _TOKEN_RE.finditer(plain)}
    return frozenset(tokens - _BOILERPLATE_LABELS)


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Jaccard двух наборов токенов; 0.0 если оба пусты (не делим на ноль)."""
    sa = set(a)
    sb = set(b)
    union = sa | sb
    if not union:
        return 0.0
    return len(sa & sb) / len(union)


@runtime_checkable
class TextCandidate(Protocol):
    """Кандидат для сравнения: минимум — id и текст вакансии (Job удовлетворяет структурно)."""

    id: int | None
    vacancy_text: str


_T = TypeVar("_T", bound=TextCandidate)


def find_duplicate(
    incoming_text: str,
    candidates: Sequence[_T],
    *,
    threshold: float = DUP_THRESHOLD,
) -> _T | None:
    """Вернуть кандидата с максимальным Jaccard > порога, иначе None.

    Кандидатов передаёт вызывающий уже префильтрованными по `jobs.text_tokens` — здесь только
    точное сравнение в Python. При равенстве берём первого (порядок — от префильтра по степени
    пересечения, т.е. наиболее похожий раньше). Дженерик сохраняет тип кандидата (напр. Job).
    """
    incoming = canonical_tokens(incoming_text)
    if not incoming:
        return None
    best: _T | None = None
    best_score = 0.0
    for cand in candidates:
        score = jaccard(incoming, canonical_tokens(cand.vacancy_text))
        if score > best_score:
            best = cand
            best_score = score
    if best is not None and best_score > threshold:
        return best
    return None


def tokens_array(text: str) -> list[str]:
    """Сортированный список канонических токенов — для колонки `jobs.text_tokens`."""
    return sorted(canonical_tokens(text))


__all__ = [
    "DUP_THRESHOLD",
    "TextCandidate",
    "canonical_tokens",
    "find_duplicate",
    "jaccard",
    "strip_html",
    "tokens_array",
]
