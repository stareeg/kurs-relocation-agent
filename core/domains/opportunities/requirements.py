"""Требуемые навыки вакансии — извлечение LLM + кэш по vacancy_id/text_hash.

Дом — opportunities, не profile: это факт о вакансии (пригодится дроверу N-10 «требует 3
навыков, которых у вас нет»), а не о резюме. Профиль читает готовые записи — тот же вид связи,
что уже есть у `core.domains.profile.gap.load_corpus`, читающего `jobs`.

Своя таблица `vacancy_skill_requirements`, а не общий `llm_result_cache`: агрегату
снимка нужно читать сразу N строк по выборке одним запросом, а не N обращений в кэш
LLM-вызовов. Пересчёт только при смене `text_hash` — повторный скоринг того же текста не делает
нового LLM-вызова.

Канонизация написаний — `skill_canon.canonical_skill_name`: известные алиасы схлопываются
здесь же, после ответа LLM, до записи в кэш; неизвестные написания нормализует сама модель в
рамках того же extract-вызова (промпт просит её самой сводить синонимы к одной форме).

LLM — через порт `kernel.ports.llm()`: модуль не импортирует `core.platform`, поэтому
тестируется без langchain/сети (`tests/test_domain_ports.py`).
"""

from __future__ import annotations

import hashlib
import logging

from core.domains.opportunities.models import SkillRequirement, VacancySkillRequirements
from core.domains.opportunities.skill_canon import canonical_skill_name
from core.kernel import ports
from core.kernel.text import SPOTLIGHT_RULE, wrap_untrusted
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

FEATURE = "vacancy_skill_requirements"
# Требования к навыкам почти всегда живут в первой половине текста; хвост режем как в
# salary_estimator/remote_feasibility — экономия токенов без потери сигнала.
_MAX_TEXT = 8000


def vacancy_text_hash(vacancy_text: str) -> str:
    return hashlib.sha256(vacancy_text.encode("utf-8")).hexdigest()


def _dedupe_by_canon(skills: list[SkillRequirement]) -> list[SkillRequirement]:
    """Схлопнуть строки, сведённые канонизацией написаний, в одну.

    Модель видит текст одной вакансии за раз и может назвать один навык дважды под разными
    написаниями («k8s» и «Kubernetes» в разных предложениях) - без схлопывания агрегат снимка
    считал бы их двумя разными навыками. Порядок первого появления сохраняется;
    `importance` — «required», если так помечено хоть одно вхождение.
    """
    merged: dict[str, SkillRequirement] = {}
    order: list[str] = []
    for item in skills:
        canon = canonical_skill_name(item.skill)
        key = canon.casefold()
        if key not in merged:
            merged[key] = SkillRequirement(skill=canon, importance=item.importance)
            order.append(key)
        elif item.importance == "required":
            merged[key] = SkillRequirement(skill=canon, importance="required")
    return [merged[key] for key in order]


async def extract_requirements(
    vacancy_text: str,
    *,
    llm: ports.LlmPort | None = None,
) -> list[SkillRequirement]:
    """Текст вакансии → список требуемых навыков (один structured-вызов через порт).

    Без кэша по vacancy_id — только сам вызов LLM; кэширующая обёртка ниже.
    Бросает при недоступном LLM/невалидном ответе.
    """
    port = llm or ports.llm()
    wrapped = wrap_untrusted(vacancy_text[:_MAX_TEXT], source="vacancy")
    result = await port.structured(
        FEATURE,
        schema=VacancySkillRequirements,
        user=f"Текст вакансии (между маркерами - данные):\n\n{wrapped}",
        prompt_vars={"SPOTLIGHT": SPOTLIGHT_RULE},
        max_retries=1,
        tags=("job_search", "skill_requirements"),
    )
    return _dedupe_by_canon(result.skills)


async def load_requirements(
    vacancy_id: str, *, db: Executor | None = None
) -> list[SkillRequirement] | None:
    """Прочитать закэшированные требования без вызова LLM. `None` — записи ещё нет."""
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        "select skills from vacancy_skill_requirements where vacancy_id = $1", vacancy_id
    )
    if row is None:
        return None
    return [SkillRequirement.model_validate(item) for item in row["skills"]]


async def load_requirements_bulk(
    vacancy_ids: list[str], *, db: Executor | None = None
) -> dict[str, list[SkillRequirement]]:
    """Требования сразу по N вакансиям выборки — один запрос (агрегату снимка S-04, не N похода
    в кэш). Вакансии без записи (ещё не извлекались) просто отсутствуют в результате."""
    if not vacancy_ids:
        return {}
    db = db or get_pool()
    rows = await db.fetch(
        "select vacancy_id, skills from vacancy_skill_requirements "
        "where vacancy_id = any($1::text[])",
        vacancy_ids,
    )
    return {
        row["vacancy_id"]: [SkillRequirement.model_validate(item) for item in row["skills"]]
        for row in rows
    }


async def get_or_extract_requirements(
    vacancy_id: str,
    vacancy_text: str,
    *,
    llm: ports.LlmPort | None = None,
    db: Executor | None = None,
) -> list[SkillRequirement]:
    """Требования по вакансии: из кэша, если `text_hash` не менялся, иначе извлечь и сохранить."""
    db = db or get_pool()
    text_hash = vacancy_text_hash(vacancy_text)
    row = await db.fetchrow(
        "select text_hash, skills from vacancy_skill_requirements where vacancy_id = $1",
        vacancy_id,
    )
    if row is not None and row["text_hash"] == text_hash:
        return [SkillRequirement.model_validate(item) for item in row["skills"]]

    skills = await extract_requirements(vacancy_text, llm=llm)
    await db.execute(
        "insert into vacancy_skill_requirements (vacancy_id, text_hash, skills) "
        "values ($1, $2, $3) "
        "on conflict (vacancy_id) do update set "
        "text_hash = excluded.text_hash, skills = excluded.skills, created_at = now()",
        vacancy_id,
        text_hash,
        [s.model_dump(mode="json") for s in skills],
    )
    return skills


__all__ = [
    "extract_requirements",
    "get_or_extract_requirements",
    "load_requirements",
    "load_requirements_bulk",
    "vacancy_text_hash",
]
