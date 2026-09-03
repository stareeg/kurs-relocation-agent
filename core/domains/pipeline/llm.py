"""LLM-фичи домена pipeline (реестр LlmFeature — A-06/A-09).

Схемы structured-выхода передаются в `ports.llm().structured()` на call-site: импорт HRFacts/ParsedDump сюда
тянет циклы через package init / соседние модули.
"""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

COVER_LETTER = register(
    LlmFeature(
        name="cover_letter",
        tier="basic",
        temperature=0.6,
        max_tokens=2048,
        budget_ms=45_000,
        retries=1,
        prompt_in_code=True,
    )
)
# Э4.4 dual_employment_and_contracting_2026.md: письмо под международный рынок (US/EU/EMEA) —
# отдельная фича, не ветка cover_letter: два разных набора правил в одном промпте деградируют
# в кашу. advanced + reasoning_effort — письмо-мост «опыт → боль вакансии» это рассуждение,
# тот же класс, что screening_pitch (L-14).
COVER_LETTER_INTL = register(
    LlmFeature(
        name="cover_letter_intl",
        tier="advanced",
        reasoning_effort="medium",
        temperature=0.4,
        max_tokens=2048,
        budget_ms=60_000,
        retries=1,
        prompt_in_code=True,
        cache_prefix=True,
    )
)
HR_DIRECTION = register(
    LlmFeature(
        name="hr_direction",
        tier="basic",
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
HR_PARSE = register(
    LlmFeature(
        name="hr_parse",
        tier="basic",
        temperature=0.0,
        max_tokens=2048,
        budget_ms=30_000,
        retries=1,
        prompt_in_code=True,
    )
)
HR_SEGMENT = register(
    LlmFeature(
        name="hr_segment",
        tier="basic",
        max_tokens=1024,
        budget_ms=30_000,
        retries=1,
        prompt_in_code=True,
    )
)
EVENT_EXTRACT = register(
    LlmFeature(
        name="event_extract",
        tier="basic",
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
FUNNEL = register(
    LlmFeature(
        name="funnel",
        tier="basic",
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
STAGE_TYPE = register(
    LlmFeature(
        name="stage_type",
        tier="basic",
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
CHANNEL_VACANCY_PARSE = register(
    LlmFeature(
        name="channel_vacancy_parse",
        tier="basic",
        temperature=0.0,
        max_tokens=2048,
        budget_ms=30_000,
        retries=1,
        prompt_in_code=True,
    )
)
HR_FACTS = register(
    LlmFeature(
        name="hr_facts",
        tier="basic",
        temperature=0.1,
        max_tokens=2048,
        budget_ms=30_000,
        retries=1,
        prompt_in_code=True,
    )
)
HR_IMPORT = register(
    LlmFeature(
        name="hr_import",
        tier="basic",
        temperature=0.0,
        max_tokens=4096,
        budget_ms=45_000,
        retries=1,
        prompt_in_code=True,
    )
)
ARCHIVE_DISPOSITION = register(
    LlmFeature(
        name="archive_disposition",
        tier="basic",
        temperature=0.0,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
# Фаза 3.2 (auto_apply_roadmap_2026_08_17.md) — ответы на анкету работодателя при отклике.
# tier=advanced + reasoning_effort="medium" (не "basic", как остальной pipeline) — те же
# основания, что у screening_questions (preparation/llm.py): ответы должны точно отражать
# факты резюме, а не звучать правдоподобно — цена ошибки выше, чем у обычного письма.
ANKETA_ANSWER = register(
    LlmFeature(
        name="anketa_answer",
        tier="advanced",
        temperature=0.3,
        max_tokens=2048,
        budget_ms=45_000,
        retries=1,
        reasoning_effort="medium",
        prompt_in_code=True,
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    COVER_LETTER,
    COVER_LETTER_INTL,
    HR_DIRECTION,
    HR_PARSE,
    HR_SEGMENT,
    EVENT_EXTRACT,
    FUNNEL,
    STAGE_TYPE,
    CHANNEL_VACANCY_PARSE,
    HR_FACTS,
    HR_IMPORT,
    ARCHIVE_DISPOSITION,
    ANKETA_ANSWER,
)

__all__ = [
    "FEATURES",
    "COVER_LETTER",
    "COVER_LETTER_INTL",
    "HR_DIRECTION",
    "HR_PARSE",
    "HR_SEGMENT",
    "EVENT_EXTRACT",
    "FUNNEL",
    "STAGE_TYPE",
    "CHANNEL_VACANCY_PARSE",
    "HR_FACTS",
    "HR_IMPORT",
    "ARCHIVE_DISPOSITION",
    "ANKETA_ANSWER",
]
