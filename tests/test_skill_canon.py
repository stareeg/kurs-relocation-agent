"""S-03 (`plans/skills_2026_07_28.md`): канон написаний навыков.

Три написания одного навыка должны сходиться в один канон, а сверка с `key_skills` - идти по
канону, а не по `casefold()`/`lower()` в лоб (дефект 1, раздел 0 плана: сравнение с учётом
регистра пропускало совпадения).
"""

from __future__ import annotations

from core.domains.opportunities.skill_canon import (
    canonical_skill_name,
    skill_in,
    skills_match,
)


def test_kubernetes_spellings_converge_to_one_canon():
    assert canonical_skill_name("k8s") == "Kubernetes"
    assert canonical_skill_name("Kubernetes") == "Kubernetes"
    assert canonical_skill_name("кубер") == "Kubernetes"
    assert canonical_skill_name("K8S") == "Kubernetes"


def test_vector_database_spellings_converge_to_one_canon():
    assert canonical_skill_name("Vector DB") == "Vector Database"
    assert canonical_skill_name("векторная БД") == "Vector Database"
    assert canonical_skill_name("Vector Database") == "Vector Database"


def test_unknown_spelling_passes_through_unchanged():
    # Неизвестные написания канон не трогает - их нормализует сама модель в S-02.
    assert canonical_skill_name("LangGraph") == "LangGraph"
    assert canonical_skill_name("  Figma  ") == "Figma"


def test_skills_match_is_case_and_alias_insensitive():
    assert skills_match("k8s", "Kubernetes")
    assert skills_match("KUBERNETES", "кубер")
    assert not skills_match("Kubernetes", "Docker")


def test_skill_in_checks_by_canon_not_raw_lowercase():
    # Дефект 1 (раздел 0): сравнение `missing.filter(c => !currentSkills.includes(c.name))`
    # было чувствительно к регистру - "kubernetes" в key_skills не гасило чип "Kubernetes".
    key_skills = ["Python", "kubernetes", "SQL"]
    assert skill_in("Kubernetes", key_skills)
    assert skill_in("k8s", key_skills)
    assert not skill_in("Go", key_skills)
