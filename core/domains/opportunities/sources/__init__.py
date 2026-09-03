"""Адаптеры источников вакансий: `VacancySource` для hh, getmatch и habr.

Новый источник = один файл в этом пакете + регистрация в `register_builtin_sources`
(вызывается из `core.app.wiring.wire_default_ports`).
"""

from __future__ import annotations

from core.domains.opportunities.models import VacancyInput
from core.domains.opportunities.sources.getmatch import (
    GetmatchVacancySource,
    extract_getmatch_numeric_id_from_text,
)
from core.domains.opportunities.sources.habr import (
    HabrVacancySource,
    extract_habr_numeric_id_from_text,
)
from core.domains.opportunities.sources.hh import HhVacancySource, discover_from_search_url
from core.kernel import ports
from core.kernel.vacancy import RawVacancy


def to_vacancy_input(raw: RawVacancy) -> VacancyInput:
    """`RawVacancy` → вход скоринга/персиста."""
    return VacancyInput(
        text=raw.text,
        url=raw.url or None,
        vacancy_id=raw.vacancy_id or None,
        title=raw.title or None,
        company=raw.company or None,
        salary_text=raw.salary_text or None,
        area=raw.area or None,
        work_format=raw.work_format or None,
        source=raw.source or None,
        skills=raw.skills,
        specialization=raw.specialization,
        seniority=raw.seniority,
    )


def register_builtin_sources(*, overwrite: bool = False) -> None:
    """Зарегистрировать hh, getmatch и habr в реестре портов."""
    ports.bind(
        vacancy_sources={
            "hh": HhVacancySource(),
            "getmatch": GetmatchVacancySource(),
            "habr": HabrVacancySource(),
        },
        overwrite=overwrite,
    )


__all__ = [
    "GetmatchVacancySource",
    "HabrVacancySource",
    "HhVacancySource",
    "discover_from_search_url",
    "extract_getmatch_numeric_id_from_text",
    "extract_habr_numeric_id_from_text",
    "register_builtin_sources",
    "to_vacancy_input",
]
