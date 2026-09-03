"""Схема одной находки HH-поиска — выход парсера SERP hh.ru
(`core.domains.opportunities.sources.hh`)."""

from __future__ import annotations

from pydantic import BaseModel


class DiscoveredVacancy(BaseModel):
    vacancy_id: str
    url: str
    title: str
    company: str = ""
    salary_text: str = ""
    area: str = ""
    # work_format - формат работы (удалённо/гибрид/офис) из новой таксономии hh `workFormats`;
    # work_schedule - legacy `@workSchedule` (смешивает формат и график: fullDay/remote/shift…),
    # держим для совместимости, но для скоринга-текста используем именно work_format.
    work_format: str = ""
    work_schedule: str = ""
    total_responses: int | None = None
    letter_required: bool | None = None
    employer_id: str | None = None
    description: str = ""
    source: str = "search_batch"

    def build_text(self) -> str:
        parts = [
            self.title,
            f"Компания: {self.company}" if self.company else "",
            f"Зарплата: {self.salary_text}" if self.salary_text else "",
            f"Локация: {self.area}" if self.area else "",
            f"Формат работы: {self.work_format}" if self.work_format else "",
        ]
        if self.description:
            parts.append("")
            parts.append(self.description)
        return "\n".join(p for p in parts if p).strip()
