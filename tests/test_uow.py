"""A-17: репозитории как порты + Unit of Work.

Проверка из плана: сценарий с ошибкой в середине не оставляет полузаписи.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from core.app.uow import MemoryStore, MemoryUnitOfWork
from core.domains.opportunities.jobs import ApplicationStage, Job, JobLink
from core.domains.opportunities.ports import JobsRepository
from core.kernel import ports
from core.kernel.errors import PortNotBoundError
from core.kernel.uow import UnitOfWork


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


# --------------------------------------------------------------------------- memory repo


@dataclass
class _MemJobs:
    """In-memory JobsRepository на MemoryStore (ключ tables['jobs'] / ['stages'])."""

    store: MemoryStore
    _seq: int = 0

    def _jobs(self) -> dict[Any, Job]:
        return self.store.table("jobs")

    def _stages(self) -> dict[Any, ApplicationStage]:
        return self.store.table("stages")

    async def save(self, job: Job, *, preserve_status: bool = False) -> Job:
        _ = preserve_status
        self._seq += 1
        job_id = job.id or self._seq
        saved = job.model_copy(update={"id": job_id})
        key = saved.vacancy_id or job_id
        self._jobs()[key] = saved
        return saved

    async def add_stage(
        self,
        job_id: int,
        stage: str,
        *,
        source: str = "manual",
        applied_at: str | None = None,
    ) -> ApplicationStage:
        _ = applied_at
        jobs = self._jobs()
        found = next((j for j in jobs.values() if j.id == job_id), None)
        if found is None:
            raise KeyError(f"job {job_id} not found")
        # зеркало status, как в SQL add_stage
        jobs[found.vacancy_id or job_id] = found.model_copy(update={"status": stage})
        self._seq += 1
        stage_row = ApplicationStage(
            id=self._seq,
            job_id=job_id,
            stage=stage,
            source=source,
            changed_at=datetime.now(UTC),
        )
        self._stages()[stage_row.id] = stage_row
        return stage_row

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None:
        return self._jobs().get(vacancy_id)

    async def find_duplicate_candidates(
        self, tokens: list[str], *, limit: int = 20
    ) -> list[Job]:
        return [j for j in self._jobs().values() if j.vacancy_text.strip()]

    async def add_job_link(
        self,
        job_id: int,
        *,
        source: str,
        vacancy_id: str | None,
        url: str | None,
        is_primary: bool = False,
    ) -> JobLink:
        self._seq += 1
        return JobLink(
            id=self._seq,
            job_id=job_id,
            source=source,
            vacancy_id=vacancy_id,
            url=url,
            is_primary=is_primary,
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
        for key, j in self._jobs().items():
            if j.id == job_id:
                updates: dict[str, Any] = {}
                if not j.salary_text and salary_text:
                    updates["salary_text"] = salary_text
                if not j.title and title:
                    updates["title"] = title
                if not j.company and company:
                    updates["company"] = company
                if not j.work_format and work_format:
                    updates["work_format"] = work_format
                if not j.published_at and published_at:
                    updates["published_at"] = published_at
                if not j.url and url:
                    updates["url"] = url
                if not j.vacancy_text.strip() and vacancy_text:
                    updates["vacancy_text"] = vacancy_text
                updated = j.model_copy(update=updates)
                self._jobs()[key] = updated
                return updated
        return None


@dataclass
class _FailAfterSave:
    """Декоратор: save проходит, add_stage всегда падает — имитация сбоя в середине."""

    inner: JobsRepository

    async def save(self, job: Job, *, preserve_status: bool = False) -> Job:
        return await self.inner.save(job, preserve_status=preserve_status)

    async def add_stage(
        self,
        job_id: int,
        stage: str,
        *,
        source: str = "manual",
        applied_at: str | None = None,
    ) -> ApplicationStage:
        raise RuntimeError("сбой после первой записи")

    async def get_by_vacancy_id(self, vacancy_id: str) -> Job | None:
        return await self.inner.get_by_vacancy_id(vacancy_id)

    async def find_duplicate_candidates(
        self, tokens: list[str], *, limit: int = 20
    ) -> list[Job]:
        return await self.inner.find_duplicate_candidates(tokens, limit=limit)

    async def add_job_link(
        self,
        job_id: int,
        *,
        source: str,
        vacancy_id: str | None,
        url: str | None,
        is_primary: bool = False,
    ) -> JobLink:
        return await self.inner.add_job_link(
            job_id, source=source, vacancy_id=vacancy_id, url=url, is_primary=is_primary
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
        return await self.inner.enrich_job(
            job_id,
            salary_text=salary_text,
            title=title,
            company=company,
            work_format=work_format,
            published_at=published_at,
            url=url,
            vacancy_text=vacancy_text,
        )


async def _scenario_job_and_stage(
    uow: UnitOfWork,
    job: Job,
    stage: str,
    *,
    fail_after_save: bool = False,
) -> Job:
    """Мини-сценарий «две таблицы»: как persist_scored, но без событий/скоринга."""
    base: JobsRepository = _MemJobs(uow.session)
    repo: JobsRepository = _FailAfterSave(base) if fail_after_save else base
    saved = await repo.save(job)
    assert saved.id is not None
    await repo.add_stage(saved.id, stage, source="test")
    return saved


def _sample_job(vacancy_id: str = "v-1") -> Job:
    return Job(vacancy_id=vacancy_id, vacancy_text="текст вакансии", title="Lead")


# --------------------------------------------------------------------------- контракт


def test_unit_of_work_protocol_is_runtime_checkable():
    assert isinstance(MemoryUnitOfWork(), UnitOfWork)


def test_uow_unbound_raises(monkeypatch: pytest.MonkeyPatch):
    # Без автосвязывания — иначе wiring подставит PostgresUnitOfWork.
    monkeypatch.setattr(ports, "_autowire", lambda: None)
    with pytest.raises(PortNotBoundError, match="UoW"):
        ports.uow()


def test_wire_default_ports_binds_uow_factory():
    from core.app.uow import PostgresUnitOfWork
    from core.app.wiring import wire_default_ports

    wire_default_ports(force=True)
    assert ports.current().uow_factory is PostgresUnitOfWork
    assert isinstance(ports.uow(), PostgresUnitOfWork)


def test_pg_jobs_repository_satisfies_protocol():
    from core.domains.opportunities.repo import PgJobsRepository

    repo = PgJobsRepository(db=object(), account_id=1)  # type: ignore[arg-type]
    assert isinstance(repo, JobsRepository)


def test_pg_offers_repository_satisfies_protocol():
    from core.domains.offers.ports import OffersRepository
    from core.domains.offers.repo import PgOffersRepository

    repo = PgOffersRepository(db=object(), account_id=1)  # type: ignore[arg-type]
    assert isinstance(repo, OffersRepository)


# --------------------------------------------------------------------------- приёмка плана


async def test_mid_scenario_failure_leaves_no_partial_writes():
    """Сценарий с ошибкой в середине не оставляет полузаписи."""
    committed = MemoryStore()

    def factory() -> MemoryUnitOfWork:
        return MemoryUnitOfWork(committed)

    with ports.use_ports(uow_factory=factory):
        with pytest.raises(RuntimeError, match="сбой после первой записи"):
            async with ports.uow() as uow:
                await _scenario_job_and_stage(
                    uow, _sample_job(), "Просмотрена", fail_after_save=True
                )

    assert committed.table("jobs") == {}
    assert committed.table("stages") == {}


async def test_successful_scenario_commits_both_writes():
    committed = MemoryStore()

    def factory() -> MemoryUnitOfWork:
        return MemoryUnitOfWork(committed)

    with ports.use_ports(uow_factory=factory):
        async with ports.uow() as uow:
            saved = await _scenario_job_and_stage(uow, _sample_job("v-ok"), "Отклик")

    assert saved.id is not None
    jobs = committed.table("jobs")
    assert "v-ok" in jobs
    assert jobs["v-ok"].status == "Отклик"
    assert len(committed.table("stages")) == 1


async def test_memory_uow_isolates_concurrent_boundaries():
    """Два последовательных UoW на одном store: откат второго не трогает первый commit."""
    store = MemoryStore()

    async with MemoryUnitOfWork(store) as uow1:
        await _scenario_job_and_stage(uow1, _sample_job("a"), "Просмотрена")

    with pytest.raises(RuntimeError):
        async with MemoryUnitOfWork(store) as uow2:
            await _scenario_job_and_stage(
                uow2, _sample_job("b"), "Отклик", fail_after_save=True
            )

    assert set(store.table("jobs")) == {"a"}
    assert "b" not in store.table("jobs")
