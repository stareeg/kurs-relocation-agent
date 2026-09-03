"""LLM-фичи домена opportunities (реестр LlmFeature — A-06/A-09).

Живые вызовы: scorer, salary_estimator/async, remote_feasibility, companies.normalize.
Схемы — только из `models` (без циклов llm ↔ salary_estimator/prompt).
"""

from __future__ import annotations

from core.domains.opportunities.models import (
    RemoteFeasibility,
    ScoreResult,
    VacancySkillRequirements,
    VacancyWorkTerms,
)
from core.platform.llm.registry import LlmFeature, register

# Канонические пути промптов (относительно корня репо). Не дублировать в CoreSettings.
INSTRUCTIONS = "prompts/opportunities/instructions.md"
JOB_SEARCH_SYSTEM = "prompts/opportunities/system.md"
REMOTE_FEASIBILITY = "prompts/opportunities/remote.md"
COMPANY_NORMALIZE = "prompts/opportunities/normalize_brand.md"
WEIGHTS_SPEC = "prompts/opportunities/weights_spec.yaml"
SKILL_REQUIREMENTS = "prompts/opportunities/skill_requirements_system.md"
TEXT_FORMAT = "prompts/opportunities/text_format.md"
WORK_TERMS = "prompts/opportunities/work_terms.md"

JOB_SEARCH = register(
    LlmFeature(
        name="job_search",
        tier="basic",
        prompt=JOB_SEARCH_SYSTEM,
        schema=ScoreResult,
        cache_prefix=True,
        temperature=0.3,
        max_tokens=2048,
        # 45s резал p90 (21s) впритык — было 2.8% видимых 502 в расширении на самых
        # медленных ответах (37.7s макс.). HTTP-таймаут и фронт/расширение уже ≥60s
        # (chat_model_for считает request_timeout от budget_ms; extension /score без
        # своего таймера) — только эта константа была тесной.
        budget_ms=60_000,
        retries=1,
    )
)
SALARY_ESTIMATE = register(
    LlmFeature(
        name="salary_estimate",
        tier="advanced",
        temperature=0.2,
        max_tokens=2048,
        budget_ms=75_000,
        retries=1,
        reasoning_effort="medium",  # L-14
        prompt_in_code=True,
        # schema=SalaryEstimate передаётся в run() — класс живёт в salary_estimator
        # (импорт сюда даёт цикл llm → estimator → prompt → llm).
    )
)
REMOTE_FEASIBILITY_FEAT = register(
    LlmFeature(
        name="remote_feasibility",
        tier="basic",
        prompt=REMOTE_FEASIBILITY,
        schema=RemoteFeasibility,
        temperature=0.1,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
    )
)
COMPANY_NORMALIZE_FEAT = register(
    LlmFeature(
        name="company_normalize",
        tier="basic",
        prompt=COMPANY_NORMALIZE,
        temperature=0.1,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
    )
)
SKIP_REASON_BACKFILL = register(
    LlmFeature(
        name="skip_reason_backfill",
        tier="basic",
        temperature=0.0,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
SKIP_REASONS_GEN = register(
    LlmFeature(
        name="skip_reasons_gen",
        tier="basic",
        temperature=0.2,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
        # schema=SkipReasonsPack передаётся в run() — класс живёт в models.
    )
)
SKILL_REQUIREMENTS_FEAT = register(
    LlmFeature(
        name="vacancy_skill_requirements",
        tier="basic",
        prompt=SKILL_REQUIREMENTS,
        schema=VacancySkillRequirements,
        temperature=0.1,
        max_tokens=2048,
        budget_ms=45_000,
        retries=1,
        # basic, не advanced — вычленение, не рассуждение.
    )
)

TEXT_FORMAT_FEAT = register(
    LlmFeature(
        name="vacancy_text_format",
        tier="basic",
        prompt=TEXT_FORMAT,
        temperature=0.1,
        max_tokens=4096,
        budget_ms=30_000,
        retries=1,
        # basic, не advanced — переразметка текста, не суждение.
    )
)
WORK_TERMS_FEAT = register(
    LlmFeature(
        name="vacancy_work_terms",
        tier="basic",
        prompt=WORK_TERMS,
        schema=VacancyWorkTerms,
        temperature=0.1,
        max_tokens=2048,
        budget_ms=30_000,
        retries=1,
        # reasoning_effort=None намеренно: вычленение фактов, не рассуждение (L-14).
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    JOB_SEARCH,
    SALARY_ESTIMATE,
    REMOTE_FEASIBILITY_FEAT,
    COMPANY_NORMALIZE_FEAT,
    SKIP_REASON_BACKFILL,
    SKIP_REASONS_GEN,
    SKILL_REQUIREMENTS_FEAT,
    TEXT_FORMAT_FEAT,
    WORK_TERMS_FEAT,
)

PROMPT_PATHS: dict[str, str] = {
    "instructions": INSTRUCTIONS,
    "job_search_system": JOB_SEARCH_SYSTEM,
    "remote_feasibility": REMOTE_FEASIBILITY,
    "company_normalize": COMPANY_NORMALIZE,
    "weights_spec": WEIGHTS_SPEC,
    "skill_requirements": SKILL_REQUIREMENTS,
    "text_format": TEXT_FORMAT,
    "work_terms": WORK_TERMS,
}

__all__ = [
    "FEATURES",
    "INSTRUCTIONS",
    "JOB_SEARCH_SYSTEM",
    "REMOTE_FEASIBILITY",
    "COMPANY_NORMALIZE",
    "WEIGHTS_SPEC",
    "SKILL_REQUIREMENTS",
    "TEXT_FORMAT",
    "WORK_TERMS",
    "JOB_SEARCH",
    "SALARY_ESTIMATE",
    "REMOTE_FEASIBILITY_FEAT",
    "COMPANY_NORMALIZE_FEAT",
    "SKIP_REASON_BACKFILL",
    "SKIP_REASONS_GEN",
    "SKILL_REQUIREMENTS_FEAT",
    "TEXT_FORMAT_FEAT",
    "WORK_TERMS_FEAT",
    "PROMPT_PATHS",
]
