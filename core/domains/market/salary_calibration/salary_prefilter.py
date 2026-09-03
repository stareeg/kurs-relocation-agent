"""Эвристики: есть ли в посте вилка / похоже на вакансию."""

from __future__ import annotations

import re

_SALARY_HINT = re.compile(
    r"(?:"
    r"\d[\d\s ]{2,}\s*(?:000|000\s*₽|₽|руб)"
    r"|от\s+\d[\d\s]{2,}"
    r"|\d+\s*[-–—]\s*\d+"
    r"|на\s+руки"
    r"|gross|нетто|до\s+вычета"
    r"|\d+\s*k\b"
    r")",
    re.IGNORECASE,
)

_VACANCY_HINT = re.compile(
    r"(?:ваканс|vacancy|hh\.ru|работа|зарплат|оклад|python|ml\b|llm|data\s+scien|"
    r"machine\s+learn|prompt|nlp|ai\b|инженер|разработчик|backend|devops)",
    re.IGNORECASE,
)

_NOISE_HINT = re.compile(
    r"(?:подписывайтесь|реклама|розыгрыш|вебинар|курс\s+со\s+скидкой|"
    r"не\s+является\s+офертой)",
    re.IGNORECASE,
)


def looks_like_salary_post(text: str) -> bool:
    raw = (text or "").strip()
    if len(raw) < 25:
        return False
    if _NOISE_HINT.search(raw) and not _SALARY_HINT.search(raw):
        return False
    return bool(_SALARY_HINT.search(raw))


def looks_like_vacancy_post(text: str) -> bool:
    raw = (text or "").strip()
    if len(raw) < 40:
        return False
    return bool(_VACANCY_HINT.search(raw) or _SALARY_HINT.search(raw))
