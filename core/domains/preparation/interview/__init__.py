"""LLM-логика подготовки к собесу и разбора собеса.

Транспорт LLM — порт `kernel.ports.llm()` (тиры — в декларациях `preparation/llm.py`).
Персист — `core.domains.preparation.{prep,interview_stages}` и
`core.domains.opportunities.enrichment` (зовут потребители, не эти модули): здесь чистая
генерация/разбор поверх `VacancyRecord`.
"""

from __future__ import annotations

from core.domains.preparation.interview.company_profiles import (
    COMPANY_PROFILES,
    CompanyProfile,
    match_company_profile,
)
from core.domains.preparation.interview.debrief import analyze_debrief
from core.domains.preparation.interview.prep import generate_prep_questions
from core.domains.preparation.interview.records import load_record, record_from_job

__all__ = [
    "generate_prep_questions",
    "analyze_debrief",
    "record_from_job",
    "load_record",
    "match_company_profile",
    "CompanyProfile",
    "COMPANY_PROFILES",
]
