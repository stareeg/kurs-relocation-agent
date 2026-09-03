"""Сырая вакансия с площадки — общий контракт для `VacancySource`.

Без I/O и без знания о hh/getmatch/habr/tg: адаптеры площадок живут в
`domains/opportunities/sources/`, а скоринг принимает уже нормализованный текст (`RawVacancy.text`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RawVacancy(BaseModel):
    """Нормализованная карточка до скоринга/персиста.

    `text` — то, что уйдёт в LLM (заголовок + мета + описание). Пустой текст допустим на
    этапе SERP-выборки; для скоринга вызывающий код обязан убедиться, что текст достаточный.
    """

    vacancy_id: str = ""
    url: str = ""
    title: str = ""
    company: str = ""
    text: str = ""
    salary_text: str = ""
    area: str = ""
    work_format: str = ""
    source: str = Field(
        default="",
        description="Имя VacancySource (hh / getmatch / …), не сырой jobs.source",
    )
    skills: list[str] | None = None
    specialization: str | None = None
    seniority: str | None = None


__all__ = ["RawVacancy"]
