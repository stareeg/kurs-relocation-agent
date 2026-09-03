"""LLM-фичи домена profile (реестр LlmFeature — A-06/A-09).

Живые вызовы: parse_pdf / strengthen / ats_fit / role_fit_llm /
weak_bullets_llm / search_profile_suggest / skill_suggest. `gap_audit` удалён —
без потребителей.

Схемы structured — на call-site (`ports.llm().structured(schema=…)`); импорт сюда из тех же
модулей даёт цикл через `profile.__init__` / ленивые импорты промптов.
"""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

STRENGTHEN_DRAFT = "prompts/profile/strengthen_system.md"
STRENGTHEN_CRITIC = "prompts/profile/critic_system.md"
STRENGTHEN_FINETUNE = "prompts/profile/finetune_system.md"
STRENGTHEN_REWRITE = "prompts/profile/strengthen_rewrite_system.md"
PARSE_PDF = "prompts/profile/parse_pdf_system.md"
ROLE_FIT = "prompts/profile/role_fit.md"
SCORE_AUDIT = "prompts/profile/score_audit.md"
SKILL_SUGGEST = "prompts/profile/skill_suggest_system.md"
INTL_EXPERIENCE = "prompts/profile/intl_experience.md"
EMPLOYER_DESCRIPTOR_PROMPT = "prompts/profile/employer_descriptor.md"

RESUME_PARSE_PDF = register(
    LlmFeature(
        name="resume_parse_pdf",
        tier="reserve",
        prompt=PARSE_PDF,
        cache_prefix=True,  # L-11
        max_tokens=4096,
        budget_ms=45_000,
        retries=1,
    )
)
RESUME_STRENGTHEN = register(
    LlmFeature(
        name="resume_strengthen",
        tier="reserve",
        prompt=STRENGTHEN_DRAFT,
        cache_prefix=True,  # L-11
        temperature=0.5,
        max_tokens=4096,
        budget_ms=120_000,
        retries=1,
    )
)
RESUME_STRENGTHEN_CRITIC = register(
    LlmFeature(
        name="resume_strengthen_critic",
        tier="reserve",
        prompt=STRENGTHEN_CRITIC,
        cache_prefix=True,  # L-11
        temperature=0.3,
        max_tokens=2048,
        budget_ms=75_000,
        retries=1,
    )
)
RESUME_ROLE_FIT = register(
    LlmFeature(
        name="resume_role_fit",
        tier="reserve",
        prompt=ROLE_FIT,
        cache_prefix=True,  # L-11
        max_tokens=1024,
        budget_ms=30_000,
        retries=1,
    )
)
RESUME_SCORE_AUDIT = register(
    LlmFeature(
        name="resume_score_audit",
        tier="reserve",
        prompt=SCORE_AUDIT,
        cache_prefix=True,
        max_tokens=4096,
        budget_ms=45_000,
        retries=1,
    )
)
WEAK_BULLETS = register(
    LlmFeature(
        name="weak_bullets",
        tier="reserve",
        max_tokens=1024,
        # §13 (local_context_blind_spots): 17 таймаутов ровно на границе budget_ms=20с при
        # ≤5.5с у всех успешных ответов — не медленная модель, а зависший провайдер/сеть.
        # Короче budget + внешний retry (weak_bullets_llm.py) = два коротких шанса вместо
        # одного долгого простоя. 2026-08-28: 8с оказалось слишком тесно (таймауты ровно на
        # 8.3с в проде) — 15с даёт запас над реальным ответом резервной модели, сохраняя
        # смысл «короткий шанс + retry».
        budget_ms=15_000,
        retries=1,
        prompt_in_code=True,
    )
)
RESUME_SEARCH_PROFILE_SUGGEST = register(
    LlmFeature(
        name="resume_search_profile_suggest",
        # basic, не reserve: reserve — сеть-страховка простоя (CLAUDE.md §LLM), продуктовой фичей
        # он держался зря и давал 10.7с на кнопке «Обновить» (лог 2026-08-14 19:10, предупреждение
        # «нет ответа за 10000ms»). Задача — извлечение/структурирование, профиль ровно basic.
        tier="basic",
        # 6-8 пунктов × (label + reason ≤60) + role_kind + market_segment: 1024 обрезало хвост.
        max_tokens=2048,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
RESUME_SKILL_SUGGEST = register(
    LlmFeature(
        name="resume_skill_suggest",
        tier="reserve",
        prompt=SKILL_SUGGEST,
        cache_prefix=True,  # L-11
        max_tokens=4096,
        budget_ms=90_000,
        retries=1,
    )
)
RESUME_INTL_EXPERIENCE = register(
    LlmFeature(
        name="intl_experience",
        tier="basic",  # экстракция, не рассуждение
        prompt=INTL_EXPERIENCE,
        schema=None,  # схема на call-site (IntlExperienceSnapshot) — иначе цикл через profile
        temperature=0.1,
        max_tokens=2048,
        budget_ms=30_000,
        retries=1,
        # reasoning_effort=None намеренно: вычленение фактов (L-14)
    )
)
# Э4.1 dual_employment_and_contracting_2026.md: обобщённое описание работодателя вместо его
# названия (деперсонализация исходящих писем/резюме под международный рынок).
EMPLOYER_DESCRIPTOR = register(
    LlmFeature(
        name="employer_descriptor",
        tier="basic",  # обобщение по фактам резюме, не многошаговое рассуждение
        prompt=EMPLOYER_DESCRIPTOR_PROMPT,
        schema=None,  # схема на call-site (EmployerDescriptor) — иначе цикл через profile
        temperature=0.2,
        max_tokens=1024,
        budget_ms=30_000,
        retries=1,
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    RESUME_PARSE_PDF,
    RESUME_STRENGTHEN,
    RESUME_STRENGTHEN_CRITIC,
    RESUME_ROLE_FIT,
    RESUME_SCORE_AUDIT,
    WEAK_BULLETS,
    RESUME_SEARCH_PROFILE_SUGGEST,
    RESUME_SKILL_SUGGEST,
    RESUME_INTL_EXPERIENCE,
    EMPLOYER_DESCRIPTOR,
)

PROMPT_PATHS: dict[str, str] = {
    "strengthen_draft": STRENGTHEN_DRAFT,
    "strengthen_critic": STRENGTHEN_CRITIC,
    "strengthen_finetune": STRENGTHEN_FINETUNE,
    "strengthen_rewrite": STRENGTHEN_REWRITE,
    "parse_pdf": PARSE_PDF,
    "role_fit": ROLE_FIT,
    "score_audit": SCORE_AUDIT,
    "skill_suggest": SKILL_SUGGEST,
    "intl_experience": INTL_EXPERIENCE,
    "employer_descriptor": EMPLOYER_DESCRIPTOR_PROMPT,
}

__all__ = [
    "FEATURES",
    "STRENGTHEN_DRAFT",
    "STRENGTHEN_CRITIC",
    "STRENGTHEN_FINETUNE",
    "STRENGTHEN_REWRITE",
    "PARSE_PDF",
    "ROLE_FIT",
    "SKILL_SUGGEST",
    "EMPLOYER_DESCRIPTOR_PROMPT",
    "PROMPT_PATHS",
]
