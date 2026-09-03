"""Регресс §1 плана local_context_blind_spots_2026_08_12.md: воронка вернулась в активную
стадию — диалог, ранее заархивированный тем же авто-отказом, должен разархивироваться.

До этой правки обратного механизма не было вовсе (grep по core/ на unarchive/reopen — ноль
совпадений): job 317 («ТехВилл», vacancy_id=135719770) дважды за один день, 2026-08-12,
оставалась с hr_threads.status='archived' при jobs.status='Скрининг' после ручного возврата
на канбане — владельцу приходилось чинить руками."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities import jobs as jobs_mod
from core.domains.opportunities import service
from core.domains.pipeline import events as pipeline_events
from core.domains.pipeline import hr_threads as hr_threads_mod
from core.kernel.events import ApplicationStageChanged
from core.kernel.schemas.funnel import FunnelStatus


class _FakeExecutor:
    """Мок `Executor` для прямого юнит-теста repo-функции (без monkeypatch пула)."""

    def __init__(self, *, result: str = "UPDATE 1") -> None:
        self.result = result
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append((sql, args))
        return self.result

    async def fetchrow(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("unarchive_threads_for_vacancy must not fetchrow")

    async def fetch(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_unarchive_threads_for_vacancy_updates_archived_only() -> None:
    db = _FakeExecutor(result="UPDATE 2")
    n = await hr_threads_mod.unarchive_threads_for_vacancy("135719770", account_id=1, db=db)
    assert n == 2
    sql, args = db.calls[0]
    s = sql.lower()
    assert "status = 'active'" in s
    assert "status = 'archived'" in s
    assert args == ("135719770", 1)


@pytest.mark.asyncio
async def test_unarchive_threads_for_vacancy_empty_vacancy_id_short_circuits() -> None:
    db = _FakeExecutor()
    n = await hr_threads_mod.unarchive_threads_for_vacancy("", account_id=1, db=db)
    assert n == 0
    assert db.calls == []


@pytest.mark.asyncio
async def test_pipeline_subscriber_archives_on_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """`pipeline.events.on_application_stage_changed` архивирует HR-тред на «Отказ» — единая
    точка эффекта на `ApplicationStageChanged`, срабатывает для ЛЮБОГО источника смены стадии
    (канбан/hh-синк/авто-отказ по красному дебрифу и т.д.), не только для `set_job_stage`."""
    calls: list[tuple[str, int]] = []

    async def _fake_archive(vacancy_id: str, *, account_id: int) -> int:
        calls.append((vacancy_id, account_id))
        return 1

    monkeypatch.setattr(hr_threads_mod, "archive_threads_for_vacancy", _fake_archive)
    evt = ApplicationStageChanged(
        vacancy_id="135719770",
        job_id=317,
        stage=FunnelStatus.REJECTED.value,
        previous_stage=FunnelStatus.TECH.value,
        source="debrief_auto_reject",
        account_id=1,
    )
    await pipeline_events.on_application_stage_changed(evt)
    assert calls == [("135719770", 1)]


@pytest.mark.asyncio
async def test_pipeline_subscriber_unarchives_on_engaged_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Симметрично: возврат в активную стадию разархивирует ранее заархивированный тред."""
    calls: list[tuple[str, int]] = []

    async def _fake_unarchive(vacancy_id: str, *, account_id: int) -> int:
        calls.append((vacancy_id, account_id))
        return 1

    monkeypatch.setattr(hr_threads_mod, "unarchive_threads_for_vacancy", _fake_unarchive)
    evt = ApplicationStageChanged(
        vacancy_id="135719770",
        job_id=317,
        stage=FunnelStatus.SCREENING.value,
        previous_stage=FunnelStatus.REJECTED.value,
        source="api_kanban",
        account_id=1,
    )
    await pipeline_events.on_application_stage_changed(evt)
    assert calls == [("135719770", 1)]


def _job_row(*, id: int, vacancy_id: str, status: str | None) -> dict[str, Any]:
    return {
        "id": id,
        "vacancy_id": vacancy_id,
        "url": None,
        "title": None,
        "company": None,
        "company_canonical": None,
        "vacancy_text": "",
        "salary_text": None,
        "area": None,
        "work_format": None,
        "work_schedule": None,
        "total_responses": None,
        "letter_required": None,
        "published_at": None,
        "cover_letter_text": None,
        "employer_id": None,
        "source": "test",
        "is_archived": False,
        "status": status,
        "overall_score": None,
        "recommendation": None,
        "score_basis": "jd_only",
        "work_city": None,
        "note": None,
        "applied_at": None,
        "hr_viewed_at": None,
        "score": {},
        "salary": None,
        "remote_feasibility": None,
        "scored_at": None,
        "created_at": None,
        "updated_at": None,
    }


class _FakeJobsPool:
    """Мок пула `jobs`-таблицы для `get_job`/`add_stage` (SQL-снифинг, как в
    tests/test_hr_pending_store.py)."""

    def __init__(self, *, job_id: int, vacancy_id: str, status: str) -> None:
        self._row = _job_row(id=job_id, vacancy_id=vacancy_id, status=status)

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        s = sql.lower()
        if "select vacancy_id, status from jobs" in s:
            return {"vacancy_id": self._row["vacancy_id"], "status": self._row["status"]}
        if "insert into application_stages" in s:
            job_id, stage, source, _account_id = args
            return {"id": 1, "job_id": job_id, "stage": stage, "source": source, "changed_at": None}
        if "from jobs where id" in s:
            return dict(self._row)
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql: str, *args: Any) -> str:
        s = sql.lower()
        if s.startswith("update jobs set status"):
            self._row["status"] = args[0]
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {sql}")

    async def fetch(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


class _FakeThreadsPool:
    """Мок пула `hr_threads` — отслеживает archive/unarchive вызовы одного треда."""

    def __init__(self, *, vacancy_id: str, status: str) -> None:
        self.vacancy_id = vacancy_id
        self.status = status
        self.calls: list[str] = []

    async def execute(self, sql: str, *args: Any) -> str:
        s = sql.lower()
        vid, _account_id = args
        assert vid == self.vacancy_id
        if "status = 'active'" in s:
            self.calls.append("unarchive")
            if self.status == "archived":
                self.status = "active"
                return "UPDATE 1"
            return "UPDATE 0"
        if "status = 'archived'" in s:
            self.calls.append("archive")
            self.status = "archived"
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute on threads pool: {sql}")

    async def fetchrow(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("unexpected fetchrow on threads pool")

    async def fetch(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


@pytest.mark.asyncio
async def test_set_job_stage_unarchives_thread_on_return_to_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Job 317 сценарий: «Отказ» → «Скрининг» через канбан (`set_job_stage`) возвращает ранее
    заархивированный диалог в active."""
    jobs_pool = _FakeJobsPool(
        job_id=317, vacancy_id="135719770", status=FunnelStatus.REJECTED.value
    )
    threads_pool = _FakeThreadsPool(vacancy_id="135719770", status="archived")
    monkeypatch.setattr(jobs_mod, "get_pool", lambda: jobs_pool)
    monkeypatch.setattr(hr_threads_mod, "get_pool", lambda: threads_pool)

    job = await service.set_job_stage(317, FunnelStatus.SCREENING.value, account_id=1)

    assert job.status == FunnelStatus.SCREENING.value
    assert threads_pool.status == "active"
    assert threads_pool.calls == ["unarchive"]


@pytest.mark.asyncio
async def test_set_job_stage_to_rejected_still_archives_not_unarchives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Существующая ветка «Отказ» не задета: новая elif не срабатывает вместе со старой."""
    jobs_pool = _FakeJobsPool(
        job_id=318, vacancy_id="135719771", status=FunnelStatus.SCREENING.value
    )
    threads_pool = _FakeThreadsPool(vacancy_id="135719771", status="active")
    monkeypatch.setattr(jobs_mod, "get_pool", lambda: jobs_pool)
    monkeypatch.setattr(hr_threads_mod, "get_pool", lambda: threads_pool)

    job = await service.set_job_stage(318, FunnelStatus.REJECTED.value, account_id=1)

    assert job.status == FunnelStatus.REJECTED.value
    assert threads_pool.status == "archived"
    assert threads_pool.calls == ["archive"]
