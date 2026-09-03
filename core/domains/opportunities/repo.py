"""Доступ к данным opportunities: Protocol + Pg-реализация и re-export SQL-фасада.

Сценарий: ``async with ports.uow() as uow:`` → ``PgJobsRepository(uow.session)``.
Низкоуровневые функции (`save_job`, …) остаются для точечных чтений вне UoW.
"""

from __future__ import annotations

from core.domains.opportunities.getmatch_sync import get_getmatch_last_sync_at, mark_getmatch_sync
from core.domains.opportunities.jobs import (
    ApplicationStage,
    Job,
    JobLink,
    add_job_link,
    add_stage,
    enrich_job,
    extract_getmatch_numeric_id_from_text,
    find_duplicate_candidates,
    get_job,
    get_job_by_vacancy_id,
    list_job_links,
    list_jobs,
    resolve_job_source_group,
    save_job,
    update_job_score,
)
from core.domains.opportunities.ports import JobsRepository
from core.domains.opportunities.skipped import (
    SkippedVacancy,
    delete_skipped,
    is_skipped,
    load_skipped_list,
    save_skipped,
)
from core.platform.db.pool import Executor


class PgJobsRepository:
    """``JobsRepository`` поверх SQL-функций ``jobs.py``; ``db`` — session UoW или пул.

    ``account_id`` фиксирован на весь сценарий UoW (Этап 3, план §1) — один запрос = один
    аккаунт, поэтому личность живёт в конструкторе репозитория, а не в каждом методе Protocol
    (не ломает сигнатуры ``JobsRepository``/memory-двойника в тестах).
    """

    def __init__(self, db: Executor, *, account_id: int) -> None:
        self._db = db
        self._account_id = account_id

    async def save(self, job: Job, *, preserve_status: bool = False) -> Job:
        return await save_job(
            job, account_id=self._account_id, db=self._db, preserve_status=preserve_status
        )

    async def add_stage(
        self,
        job_id: int,
        stage: str,
        *,
        source: str = "manual",
        applied_at: str | None = None,
    ) -> ApplicationStage:
        return await add_stage(
            job_id,
            stage,
            source=source,
            applied_at=applied_at,
            account_id=self._account_id,
            db=self._db,
        )

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None:
        return await get_job_by_vacancy_id(vacancy_id, account_id=self._account_id, db=self._db)

    async def find_duplicate_candidates(self, tokens: list[str], *, limit: int = 20) -> list[Job]:
        return await find_duplicate_candidates(
            tokens, account_id=self._account_id, limit=limit, db=self._db
        )

    async def add_job_link(
        self,
        job_id: int,
        *,
        source: str,
        vacancy_id: str | None,
        url: str | None,
        is_primary: bool = False,
    ) -> JobLink:
        return await add_job_link(
            job_id,
            source=source,
            vacancy_id=vacancy_id,
            url=url,
            account_id=self._account_id,
            is_primary=is_primary,
            db=self._db,
        )

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
    ) -> Job | None:
        return await enrich_job(
            job_id,
            salary_text=salary_text,
            title=title,
            company=company,
            work_format=work_format,
            published_at=published_at,
            url=url,
            vacancy_text=vacancy_text,
            account_id=self._account_id,
            db=self._db,
        )

    async def list_job_links(self, job_ids: list[int]) -> dict[int, list[JobLink]]:
        return await list_job_links(job_ids, account_id=self._account_id, db=self._db)


__all__ = [
    "Job",
    "JobLink",
    "JobsRepository",
    "PgJobsRepository",
    "SkippedVacancy",
    "add_job_link",
    "delete_skipped",
    "enrich_job",
    "extract_getmatch_numeric_id_from_text",
    "find_duplicate_candidates",
    "get_getmatch_last_sync_at",
    "get_job",
    "get_job_by_vacancy_id",
    "is_skipped",
    "list_job_links",
    "list_jobs",
    "load_skipped_list",
    "mark_getmatch_sync",
    "resolve_job_source_group",
    "save_job",
    "save_skipped",
    "update_job_score",
]
