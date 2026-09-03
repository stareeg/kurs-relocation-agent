"""Витрина «Сегодня»: кулдаун «Ответить», архив Чатов не напоминает, созвон глушит «Напомнить»."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.app.scenarios import conversations
from core.domains.opportunities.jobs import Job
from core.domains.pipeline.hr_threads import HrThread
from core.domains.preparation.interview_stages import InterviewStage
from core.kernel.schemas.funnel import FunnelStatus

_NOW = datetime(2026, 8, 25, 15, 0, tzinfo=UTC)


def _thread(**kwargs: Any) -> HrThread:
    base: dict[str, Any] = {
        "id": 1,
        "vacancy_id": "v1",
        "status": "active",
        "last_hr_kind": "hr_in",
        "last_hr_at": _NOW - timedelta(hours=3),
    }
    base.update(kwargs)
    return HrThread(**base)


def _job(vacancy_id: str, *, status: str = FunnelStatus.SCREENING.value) -> Job:
    return Job(id=1, vacancy_id=vacancy_id, vacancy_text="x", status=status)


def test_reply_ignores_fresh_hr_in():
    fresh = _thread(last_hr_at=_NOW - timedelta(hours=1, minutes=50))
    ready = _thread(id=2, vacancy_id="v2", last_hr_at=_NOW - timedelta(hours=2))
    got = conversations._reply_bucket([fresh, ready], now=_NOW)
    assert [t.vacancy_id for t in got] == ["v2"]


def test_reply_ignores_hr_in_without_timestamp():
    got = conversations._reply_bucket([_thread(last_hr_at=None)], now=_NOW)
    assert got == []


def test_remind_needs_four_days_of_silence():
    short = _thread(last_hr_kind="hr_out", last_hr_at=_NOW - timedelta(days=3, hours=23))
    long = _thread(
        id=2, vacancy_id="v2", last_hr_kind="hr_out", last_hr_at=_NOW - timedelta(days=4)
    )
    got = conversations._remind_bucket([short, long], now=_NOW)
    assert [t.vacancy_id for t in got] == ["v2"]


def test_remind_skips_when_call_is_already_scheduled():
    waiting = _thread(
        last_hr_kind="hr_out",
        last_hr_at=_NOW - timedelta(days=6),
        next_stage_at=_NOW + timedelta(days=1),
    )
    assert conversations._remind_bucket([waiting], now=_NOW) == []


def test_remind_keeps_when_stage_already_passed():
    waiting = _thread(
        last_hr_kind="hr_out",
        last_hr_at=_NOW - timedelta(days=6),
        next_stage_at=_NOW - timedelta(hours=1),
    )
    got = conversations._remind_bucket([waiting], now=_NOW)
    assert [t.vacancy_id for t in got] == ["v1"]


class _FakeArchivedDb:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, str]]:
        self.calls.append((sql, args))
        return self.rows


async def test_list_archived_vacancy_ids_selects_archived_only() -> None:
    from core.domains.pipeline import hr_threads as hr_threads_mod

    db = _FakeArchivedDb([{"vacancy_id": "a"}, {"vacancy_id": "b"}])
    got = await hr_threads_mod.list_archived_vacancy_ids(account_id=7, db=db)
    assert got == {"a", "b"}
    sql, args = db.calls[0]
    assert "status = 'archived'" in sql.lower()
    assert args == (7,)


async def test_attention_scope_hides_archived_and_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    active = _thread(vacancy_id="live")
    skipped_live = _thread(id=2, vacancy_id="skipped")
    rejected = _thread(id=3, vacancy_id="rejected")

    async def fake_archived(*, account_id: int) -> set[str]:
        assert account_id == 7
        return {"archived"}

    async def fake_threads(*, account_id: int, include_archived: bool = False, limit: int = 200):
        assert include_archived is False
        return [active, skipped_live, rejected]

    async def fake_skipped(vids: list[str], *, account_id: int) -> set[str]:
        return {"skipped"} & set(vids)

    async def fake_jobs(vids: list[str], *, account_id: int) -> dict[str, Job]:
        return {
            "live": _job("live"),
            "skipped": _job("skipped"),
            "rejected": _job("rejected", status=FunnelStatus.REJECTED.value),
        }

    monkeypatch.setattr("core.domains.pipeline.hr_threads.list_archived_vacancy_ids", fake_archived)
    monkeypatch.setattr("core.domains.pipeline.hr_threads.list_recent_threads", fake_threads)
    monkeypatch.setattr("core.domains.opportunities.skipped.get_skipped_ids", fake_skipped)
    monkeypatch.setattr("core.domains.opportunities.jobs.get_jobs_by_vacancy_ids", fake_jobs)

    alive, hide = await conversations._attention_scope(account_id=7)
    assert [t.vacancy_id for t in alive] == ["live"]
    assert hide == {"archived", "skipped", "rejected"}


async def test_upcoming_skips_hidden_and_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    stages = [
        InterviewStage(
            vacancy_id="archived",
            stage_type="hr_screening",
            scheduled_at=_NOW + timedelta(days=1),
            format="online",
            status="scheduled",
        ),
        InterviewStage(
            vacancy_id="rejected",
            stage_type="live_coding",
            scheduled_at=_NOW + timedelta(days=2),
            format="online",
            status="scheduled",
        ),
        InterviewStage(
            vacancy_id="live",
            stage_type="theory",
            scheduled_at=_NOW + timedelta(days=3),
            format="online",
            status="scheduled",
        ),
    ]

    async def fake_stages(*, days: int, account_id: int):
        return stages

    async def fake_skipped(vids: list[str], *, account_id: int) -> set[str]:
        return set()

    async def fake_jobs(vids: list[str], *, account_id: int) -> dict[str, Job]:
        return {
            "archived": _job("archived"),
            "rejected": _job("rejected", status=FunnelStatus.REJECTED.value),
            "live": _job("live", status=FunnelStatus.TECH.value),
        }

    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.load_upcoming_stages", fake_stages
    )
    monkeypatch.setattr("core.domains.opportunities.skipped.get_skipped_ids", fake_skipped)
    monkeypatch.setattr("core.domains.opportunities.jobs.get_jobs_by_vacancy_ids", fake_jobs)

    got = await conversations._upcoming_bucket(account_id=7, hide={"archived"})
    assert [s.vacancy_id for s in got] == ["live"]


async def test_strong_unapplied_skips_archived_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = [
        _job("archived", status=FunnelStatus.VIEWED.value),
        _job("fresh", status=FunnelStatus.VIEWED.value),
    ]
    jobs[0].overall_score = 90
    jobs[1].overall_score = 85

    async def fake_strong(**_kwargs: Any) -> list[Job]:
        return jobs

    monkeypatch.setattr("core.domains.opportunities.jobs.list_strong_unapplied", fake_strong)
    got = await conversations._strong_unapplied_bucket(account_id=7, hide={"archived"})
    assert [j.vacancy_id for j in got] == ["fresh"]
