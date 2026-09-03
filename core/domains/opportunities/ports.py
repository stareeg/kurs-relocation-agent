"""Порты репозитория opportunities.

Сценарии зависят от Protocol, а не от SQL-функций. Реализация — ``PgJobsRepository``
в ``repo.py`` (рядом, за интерфейсом). В тестах — Memory-двойник на ``MemoryStore``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.domains.opportunities.jobs import ApplicationStage, Job, JobLink


@runtime_checkable
class JobsRepository(Protocol):
    """Персист вакансии и стадий воронки. Одна реализация — одна ``session`` UoW."""

    async def save(self, job: Job, *, preserve_status: bool = False) -> Job: ...

    async def add_stage(
        self,
        job_id: int,
        stage: str,
        *,
        source: str = "manual",
        applied_at: str | None = None,
    ) -> ApplicationStage: ...

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None: ...

    async def find_duplicate_candidates(
        self, tokens: list[str], *, limit: int = 20
    ) -> list[Job]: ...

    async def add_job_link(
        self,
        job_id: int,
        *,
        source: str,
        vacancy_id: str | None,
        url: str | None,
        is_primary: bool = False,
    ) -> JobLink: ...

    async def enrich_job(
        self,
        job_id: int,
        *,
        salary_text: str | None = None,
        title: str | None = None,
        company: str | None = None,
        work_format: str | None = None,
        published_at: str | None = None,
        url: str | None = None,
        vacancy_text: str | None = None,
    ) -> Job | None: ...


__all__ = ["JobLink", "JobsRepository"]
