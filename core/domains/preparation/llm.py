"""LLM-фичи домена preparation (реестр LlmFeature — A-06/A-09).

L-13: `max_tokens` режет бесконечную генерацию; `budget_ms` — реальный SLO (не душить
reasoning_pro на полуготовом ответе). `retries=1` — один ремонтный LLM-вызов (итого ≤2).
"""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

SCREENING_JD_BRIEF = "prompts/preparation/screening/jd_brief.md"
SCREENING_PITCH = "prompts/preparation/screening/pitch.md"
SCREENING_QUESTIONS = "prompts/preparation/screening/questions.md"
SCREENING_HR_QUESTIONS = "prompts/preparation/screening/hr_questions.md"
SCREENING_ORAL_STYLE = "prompts/preparation/screening/oral_style.md"
SCREENING_CHAT_SUMMARY = "prompts/preparation/screening/chat_summary.md"
PREP_TOPICS = "prompts/preparation/interview/prep_topics.md"
MAP_QUESTION_TOPICS = "prompts/preparation/interview/map_question_topics.md"
PARSE_EXTERNAL_PREP = "prompts/preparation/interview/parse_external_prep.md"
SOBES_OVERLAY = "prompts/preparation/interview/sobes_overlay.md"
PREP_TOPIC_EXPAND = "prompts/preparation/interview/topic_expand.md"

SCREENING_BRIEF_FEAT = register(
    LlmFeature(
        name="screening_brief",
        tier="basic",
        prompt=SCREENING_JD_BRIEF,
        cache_prefix=True,  # L-11: статичный jd_brief.md
        temperature=0.2,
        max_tokens=2048,  # smoke L-13: 1017/1024 — JSON brief обрезался у потолка
        budget_ms=30_000,
        retries=1,
    )
)
SCREENING_PITCH_FEAT = register(
    LlmFeature(
        name="screening_pitch",
        tier="advanced",
        prompt=SCREENING_PITCH,
        cache_prefix=True,
        temperature=0.6,
        max_tokens=4096,
        budget_ms=90_000,
        retries=1,
        reasoning_effort="medium",  # L-14
    )
)
SCREENING_QUESTIONS_FEAT = register(
    LlmFeature(
        name="screening_questions",
        tier="advanced",
        prompt=SCREENING_QUESTIONS,
        cache_prefix=True,  # L-11
        temperature=0.4,
        max_tokens=6144,  # smoke: peak ~3.3k на часть; запас под длинные JD + repair
        budget_ms=90_000,
        retries=1,
        reasoning_effort="medium",  # L-14
    )
)
PREP = register(
    LlmFeature(
        name="prep",
        tier="advanced",
        prompt=PREP_TOPICS,
        cache_prefix=True,  # L-11: резюме+правила в prefix, этап — dynamic_tail
        temperature=0.5,
        max_tokens=6144,
        budget_ms=120_000,
        retries=1,
        reasoning_effort="medium",  # L-14: дорогая генерация вопросов
        # schema generate_prep_questions — на call-site (_PrepQuestionsOut), L-12;
        # фича ещё зовёт complete для тем/чата (разные формы ответа).
    )
)
PREP_PACK = register(
    LlmFeature(
        name="prep_pack",
        tier="advanced",
        temperature=0.4,
        max_tokens=6144,
        budget_ms=120_000,
        retries=1,
        reasoning_effort="medium",  # L-14
        prompt_in_code=True,
        cache_prefix=True,  # L-11
    )
)
DEBRIEF = register(
    LlmFeature(
        name="debrief",
        tier="advanced",
        temperature=0.3,
        max_tokens=8192,
        # Согласовано с analyze_debrief(_LLM_TIMEOUT_S=150): раньше budget 35с резал живой разбор.
        budget_ms=150_000,
        retries=1,
        reasoning_effort="medium",  # L-14
        prompt_in_code=True,
        cache_prefix=True,  # L-11: резюме+рубрика статичны между разборами
    )
)
DEBRIEF_RESOLUTION = register(
    LlmFeature(
        name="debrief_resolution",
        tier="basic",
        temperature=0.1,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
NEXT_STAGE_HINT = register(
    LlmFeature(
        name="next_stage_hint",
        tier="basic",
        temperature=0.1,
        max_tokens=1024,  # L-13: пол реестра ≥1024 (контракт LlmFeature)
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
QA = register(
    LlmFeature(
        name="qa",
        tier="advanced",
        temperature=0.3,
        max_tokens=4096,
        budget_ms=75_000,
        retries=1,
        prompt_in_code=True,
        cache_prefix=True,  # L-11: build_qa_system_prompt статичен
    )
)
QUESTION_MATCH = register(
    LlmFeature(
        name="question_match",
        tier="basic",
        prompt=MAP_QUESTION_TOPICS,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
    )
)
COMPETENCY_CANON = register(
    LlmFeature(
        name="competency_canon",
        tier="basic",
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)
SCREENING_CHAT_SUMMARY_FEAT = register(
    LlmFeature(
        name="screening_chat_summary",
        tier="basic",
        prompt=SCREENING_CHAT_SUMMARY,
        temperature=0.3,
        max_tokens=1536,
        budget_ms=45_000,
        retries=1,
    )
)
# П.5c: раскрытие темы из разбора реального собеса — дешёвый basic-tier LLM-вызов по клику
# на тему в блоке «Темы». Stateless: ничего не пишем в БД, кэш через общий llm_result_cache.
PREP_TOPIC_EXPAND_FEAT = register(
    LlmFeature(
        name="prep_topic_expand",
        tier="basic",
        prompt=PREP_TOPIC_EXPAND,
        temperature=0.3,
        max_tokens=1024,  # L-13: пол реестра ≥1024 (контракт LlmFeature)
        budget_ms=20_000,
        retries=1,
        cache_prefix=True,  # L-11: правила/резюме в prefix, тема+вакансия — dynamic_tail
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    SCREENING_BRIEF_FEAT,
    SCREENING_PITCH_FEAT,
    SCREENING_QUESTIONS_FEAT,
    PREP,
    PREP_PACK,
    DEBRIEF,
    DEBRIEF_RESOLUTION,
    QA,
    QUESTION_MATCH,
    COMPETENCY_CANON,
    SCREENING_CHAT_SUMMARY_FEAT,
    PREP_TOPIC_EXPAND_FEAT,
)

PROMPT_PATHS: dict[str, str] = {
    "screening_jd_brief": SCREENING_JD_BRIEF,
    "screening_pitch": SCREENING_PITCH,
    "screening_questions": SCREENING_QUESTIONS,
    "screening_hr_questions": SCREENING_HR_QUESTIONS,
    "screening_oral_style": SCREENING_ORAL_STYLE,
    "screening_chat_summary": SCREENING_CHAT_SUMMARY,
    "prep_topics": PREP_TOPICS,
    "map_question_topics": MAP_QUESTION_TOPICS,
    "parse_external_prep": PARSE_EXTERNAL_PREP,
    "sobes_overlay": SOBES_OVERLAY,
    "prep_topic_expand": PREP_TOPIC_EXPAND,
}

__all__ = [
    "FEATURES",
    "SCREENING_JD_BRIEF",
    "SCREENING_PITCH",
    "SCREENING_QUESTIONS",
    "SCREENING_HR_QUESTIONS",
    "SCREENING_ORAL_STYLE",
    "SCREENING_CHAT_SUMMARY",
    "PREP_TOPICS",
    "MAP_QUESTION_TOPICS",
    "PARSE_EXTERNAL_PREP",
    "SOBES_OVERLAY",
    "PREP_TOPIC_EXPAND",
    "PROMPT_PATHS",
]
