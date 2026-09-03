"""Канон написаний навыков.

«k8s», «кубер» и «Kubernetes» — один и тот же навык под разными именами. Детерминированный
словарь ловит устойчивые алиасы/аббревиатуры (не owner-специфика — это общеупотребимая
техническая лексика, а не навыки конкретного кандидата, тот же принцип, что у `COMPANY_ALIASES`
в `companies/normalize.py`). Неизвестные написания нормализует сама модель при извлечении
требований — тем же extract-вызовом, без отдельного прохода
(см. `prompts/opportunities/skill_requirements_system.md`).

Потребители: `requirements.extract_requirements` (схлопывает дубли внутри одного ответа LLM),
агрегат снимка навыков и сверка с `key_skills` резюме — вместо `casefold()`/`lower()` в
лоб: «Kubernetes» из требований вакансии и «k8s» в резюме должны
считаться одним навыком, а не двумя разными строками.
"""

from __future__ import annotations

import re

__all__ = [
    "SKILL_ALIASES",
    "canonical_skill_name",
    "skill_in",
    "skills_match",
]

# Ключ - `_fold_key()` (lower + ё→е + схлопнутые пробелы); значение - канон для UI/сверки/агрегата.
# Короткий расширяемый словарь; совпадение по полному ключу (не подстрока), как COMPANY_ALIASES.
SKILL_ALIASES: dict[str, str] = {
    # Kubernetes
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "кубер": "Kubernetes",
    "кубернетес": "Kubernetes",
    "кубернетис": "Kubernetes",
    # Vector Database
    "vector db": "Vector Database",
    "vectordb": "Vector Database",
    "vector database": "Vector Database",
    "векторная бд": "Vector Database",
    "векторная база данных": "Vector Database",
    "векторная база": "Vector Database",
    # CI/CD
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "ci cd": "CI/CD",
    # Docker
    "docker": "Docker",
    "докер": "Docker",
}


def _fold_key(name: str) -> str:
    """Ключ сравнения: lower + ё→е + схлопнутые пробелы (как `companies.normalize._fold_key`)."""
    s = name.casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", s).strip()


def canonical_skill_name(skill: str) -> str:
    """Известный алиас → канон; неизвестное написание — как есть (уже нормализовано LLM в S-02)."""
    alias = SKILL_ALIASES.get(_fold_key(skill))
    return alias if alias else skill.strip()


def skills_match(a: str, b: str) -> bool:
    """Два названия - один навык? Сравнение по канону, не по сырому регистру/пробелам."""
    return _fold_key(canonical_skill_name(a)) == _fold_key(canonical_skill_name(b))


def skill_in(skill: str, others: list[str]) -> bool:
    """Есть ли навык (по канону) среди других названий - например, `key_skills` резюме."""
    return any(skills_match(skill, other) for other in others)
