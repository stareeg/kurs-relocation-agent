"""Раздел «Скрининги»: пакет самопрезентации под вакансию (защита + нападение).

Информация о кандидате уже живёт в резюме и глобальной легенде. Здесь - точечный пакет под JD:
разбор вакансии, устный рассказ блоками, мосты к вакансии, вероятные вопросы HR и острые вопросы
к HR (`core.domains.preparation.screening.pack.generate_self_pres_pack`, план 2026-07-23 шаг 8).
"""

from __future__ import annotations

from core.domains.preparation.screening.context import (
    format_self_pres_context,
    format_self_pres_for_cover_letter,
    load_self_pres_context,
)
from core.domains.preparation.screening.pack import VacancySelfPres, generate_self_pres_pack
from core.domains.preparation.screening.questions import (
    HrQuestion,
    QuestionGroup,
    ScreeningQuestion,
)

__all__ = [
    "HrQuestion",
    "QuestionGroup",
    "ScreeningQuestion",
    "VacancySelfPres",
    "format_self_pres_context",
    "format_self_pres_for_cover_letter",
    "generate_self_pres_pack",
    "load_self_pres_context",
]
