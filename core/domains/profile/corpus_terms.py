"""Термины рынка из корпуса вакансий пользователя (универсальный словарь вместо CONCEPTS).

Детерминизм: нормализация → 1-3-граммы → стоп-слова → document frequency.
Без LLM и без БД: чистая функция над списком `vacancy_text`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Корпус меньше порога → словарь не строим (слишком шумно / нестабильно).
MIN_CORPUS_SIZE = 15
# Доля вакансий, в которых термин должен встретиться (как DEMANDED_THRESHOLD в gap).
DF_THRESHOLD = 0.10

# Служебные RU + общие HR-слова вакансий (не рыночные термины специальности).
# split() удобнее длинного list-literal для словаря стоп-слов.
_STOPWORDS = frozenset(
    """
    а без более будет быть в вам вас весь во вот все всё всего всех вы где да даже для до
    его ее её если есть ещё еще же за зачем и из или им их к как какая какие какой когда
    кто ли либо лишь между менее меня мне мой мы на над надо нам нас не него нее неё нет
    ни них но ну о об однако он она они оно от очень по под при про просто с сам свое
    своего свои свой себе себя сейчас со так также такой там те тебе тем то того тоже
    только том тот ты у уже хотя чего чем что чтобы эта эти это этом этот я

    год года годы лет месяц месяца месяцев день дня дни час часа

    вакансия вакансии вакансию вакансий должность должности кандидата кандидат кандидатов
    сотрудник сотрудника сотрудников специалист специалиста специалистов
    компания компании компанию компаний организация организации организаций
    работодатель работодателя клиента клиент клиентов заказчик заказчика
    команда команды команде командой коллег коллеги коллектив коллектива
    опыт опыта опытом работы работа работу работой работ работую
    задачи задача задач задачей обязанность обязанности обязанностей
    требования требование требований условие условия условий
    навыки навык навыками знание знания знаний умение умения умений
    понимание пониманием владение владением
    развитие развития возможность возможности
    бизнес бизнеса процессы процесс процессов
    уровень уровня высокий высоких хорошее хороший отличное
    обязательно желательно плюсом преимущество преимущества
    описание раздела раздел разделы текст тексты
    россии россия рф удаленно удалённо удаленная удалённая офис офисе гибрид
    полный полная занятость график графике зарплата заработной платы оклад
    отклик отклика резюме собеседование интервью hh getmatch
    """.split()  # noqa: SIM905
)


_TOKEN_RE = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9+\-/#.]*", re.IGNORECASE)


@dataclass(frozen=True)
class CorpusTerm:
    """Один термин словаря рынка: имя, доля документов, скомпилированный regex."""

    name: str
    df: float
    pattern: re.Pattern[str]


def _normalize(text: str) -> str:
    return (text or "").casefold().replace("ё", "е")


def _tokenize(text: str) -> list[str]:
    return [m.group(0).replace("ё", "е") for m in _TOKEN_RE.finditer(_normalize(text))]


def _is_content_token(token: str) -> bool:
    if token in _STOPWORDS or token.isdigit():
        return False
    # Короткие RU-токены отсекаем; латиница (ci, go, qa) может быть термином.
    return len(token) >= 3 or any(c.isascii() and c.isalpha() for c in token)


def _ngrams(tokens: list[str], n: int) -> list[str]:
    if n <= 0 or len(tokens) < n:
        return []
    out: list[str] = []
    for i in range(len(tokens) - n + 1):
        chunk = tokens[i : i + n]
        if all(_is_content_token(t) for t in chunk):
            out.append(" ".join(chunk))
    return out


def _compile_term_pattern(name: str) -> re.Pattern[str]:
    parts = [re.escape(p) for p in name.split()]
    body = r"\s+".join(parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def extract_corpus_terms(corpus_texts: list[str]) -> list[CorpusTerm]:
    """Извлечь рыночные термины из корпуса. Пустой/маленький корпус → []."""
    n = len(corpus_texts)
    if n < MIN_CORPUS_SIZE:
        return []

    # term → множество индексов документов (document frequency).
    docs: dict[str, set[int]] = {}
    for doc_i, raw in enumerate(corpus_texts):
        tokens = _tokenize(raw)
        seen_in_doc: set[str] = set()
        for order in (1, 2, 3):
            for term in _ngrams(tokens, order):
                if term in seen_in_doc:
                    continue
                seen_in_doc.add(term)
                docs.setdefault(term, set()).add(doc_i)

    kept: list[CorpusTerm] = []
    for term, idxs in docs.items():
        df = len(idxs) / n
        if df + 1e-12 < DF_THRESHOLD:
            continue
        kept.append(CorpusTerm(name=term, df=df, pattern=_compile_term_pattern(term)))

    kept.sort(key=lambda t: (-t.df, t.name))
    return kept


__all__ = [
    "CorpusTerm",
    "DF_THRESHOLD",
    "MIN_CORPUS_SIZE",
    "extract_corpus_terms",
]
