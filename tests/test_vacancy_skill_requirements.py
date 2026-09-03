"""S-02 (`plans/skills_2026_07_28.md`): извлечение требуемых навыков вакансии + кэш по vacancy_id."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities.models import SkillRequirement, VacancySkillRequirements
from core.domains.opportunities.requirements import (
    extract_requirements,
    get_or_extract_requirements,
    load_requirements,
    vacancy_text_hash,
)
from tests.fakes import FakeLlm, RaisingLlm


class FakeDb:
    """Двойник `Executor`: одна строка на `vacancy_id`, как реальная таблица (PK)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.executes = 0

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        vacancy_id = args[0]
        return self.rows.get(vacancy_id)

    async def execute(self, query: str, *args: Any) -> str:
        self.executes += 1
        vacancy_id, text_hash, skills = args
        self.rows[vacancy_id] = {"text_hash": text_hash, "skills": skills}
        return "INSERT 0 1"

    async def executemany(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise NotImplementedError


def test_vacancy_text_hash_deterministic_and_sensitive_to_content():
    a = vacancy_text_hash("Python, 3+ года")
    b = vacancy_text_hash("Python, 3+ года")
    c = vacancy_text_hash("Python, 5+ лет")
    assert a == b
    assert a != c


@pytest.mark.asyncio
async def test_extract_requirements_calls_llm_and_wraps_text():
    llm = FakeLlm(
        result=VacancySkillRequirements(
            skills=[
                SkillRequirement(skill="Python", importance="required"),
                SkillRequirement(skill="Docker", importance="preferred"),
            ]
        )
    )
    skills = await extract_requirements("Ищем бэкенд-разработчика, нужен Python", llm=llm)
    assert [s.skill for s in skills] == ["Python", "Docker"]
    assert llm.calls[0]["feature"] == "vacancy_skill_requirements"
    # Текст вакансии - недоверенные данные, идёт через wrap_untrusted + SPOTLIGHT_RULE.
    assert "Ищем бэкенд-разработчика" in llm.calls[0]["user"]
    assert llm.calls[0]["prompt_vars"]["SPOTLIGHT"]


@pytest.mark.asyncio
async def test_extract_requirements_dedupes_by_canon_and_keeps_required():
    # Модель назвала Kubernetes дважды под разными написаниями - одна строка на выходе,
    # importance "required" побеждает "preferred" вне зависимости от порядка ответа LLM.
    llm = FakeLlm(
        result=VacancySkillRequirements(
            skills=[
                SkillRequirement(skill="k8s", importance="preferred"),
                SkillRequirement(skill="Python", importance="required"),
                SkillRequirement(skill="Kubernetes", importance="required"),
            ]
        )
    )
    skills = await extract_requirements("нужен k8s и Kubernetes, Python", llm=llm)
    assert [(s.skill, s.importance) for s in skills] == [
        ("Kubernetes", "required"),
        ("Python", "required"),
    ]


@pytest.mark.asyncio
async def test_load_requirements_missing_returns_none():
    db = FakeDb()
    assert await load_requirements("v-1", db=db) is None


@pytest.mark.asyncio
async def test_get_or_extract_requirements_writes_cache_row():
    llm = FakeLlm(
        result=VacancySkillRequirements(
            skills=[SkillRequirement(skill="SQL", importance="required")]
        )
    )
    db = FakeDb()
    skills = await get_or_extract_requirements("v-1", "нужен SQL", llm=llm, db=db)
    assert [s.skill for s in skills] == ["SQL"]
    assert db.executes == 1
    cached = await load_requirements("v-1", db=db)
    assert cached is not None
    assert [s.skill for s in cached] == ["SQL"]


@pytest.mark.asyncio
async def test_get_or_extract_requirements_cache_hit_skips_llm():
    llm = FakeLlm(
        result=VacancySkillRequirements(
            skills=[SkillRequirement(skill="SQL", importance="required")]
        )
    )
    db = FakeDb()
    await get_or_extract_requirements("v-1", "нужен SQL", llm=llm, db=db)

    # Второй прогон тем же текстом - LLM не должна дёргаться (text_hash не менялся).
    skills = await get_or_extract_requirements("v-1", "нужен SQL", llm=RaisingLlm(), db=db)
    assert [s.skill for s in skills] == ["SQL"]
    assert db.executes == 1


@pytest.mark.asyncio
async def test_get_or_extract_requirements_recomputes_on_text_change():
    db = FakeDb()
    await get_or_extract_requirements(
        "v-1",
        "нужен SQL",
        llm=FakeLlm(
            result=VacancySkillRequirements(
                skills=[SkillRequirement(skill="SQL", importance="required")]
            )
        ),
        db=db,
    )

    skills = await get_or_extract_requirements(
        "v-1",
        "нужен Go, не SQL",
        llm=FakeLlm(
            result=VacancySkillRequirements(
                skills=[SkillRequirement(skill="Go", importance="required")]
            )
        ),
        db=db,
    )
    assert [s.skill for s in skills] == ["Go"]
    assert db.executes == 2
