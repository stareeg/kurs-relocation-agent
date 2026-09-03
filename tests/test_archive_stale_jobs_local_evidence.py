"""Регресс §4 плана local_context_blind_spots_2026_08_12.md: `archive_stale_jobs` был слеп к
живой переписке и назначенным встречам — считал «последнюю активность» только по
`jobs.updated_at`/`scored_at`/`applied_at`/`created_at`, никогда не заглядывая в
`hr_messages.sent_at`/`interview_stages.scheduled_at`. Вакансия с полностью живым диалогом, по
которой просто давно не двигали стадию/скор вручную, улетала в «Отказ» тем же слепым способом,
что уже один раз сломал воронку у job 317 (см. tests/test_negotiations_local_evidence.py) —
только детерминированно, по таймеру, без единого лога-предупреждения.

Переход при этом должен идти через `add_stage` (не голым UPDATE), чтобы `application_stages`
не расходилась с `jobs.status`."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities import jobs as jobs_mod
from core.kernel.schemas.funnel import FunnelStatus


class _FakeSelectDb:
    """Мок `Executor` — отдаёт канонический список «протухших» job-строк, execute запрещён:
    после фикса §4 функция больше не должна писать статус голым UPDATE."""

    def __init__(self, *, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((sql, args))
        return self._rows

    async def fetchrow(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError("archive_stale_jobs must not fetchrow directly (add_stage owns it)")

    async def execute(self, *_a: Any, **_k: Any) -> Any:
        raise AssertionError(
            "archive_stale_jobs must not UPDATE jobs directly — route through add_stage "
            "so application_stages stays in sync (план §4)"
        )


@pytest.mark.asyncio
async def test_archive_stale_jobs_selects_via_hr_and_interview_lateral_joins() -> None:
    """Формула «последней активности» должна учитывать hr_messages и interview_stages —
    иначе живая переписка/назначенная встреча не защищают вакансию от авто-отказа."""
    db = _FakeSelectDb(rows=[])
    n = await jobs_mod.archive_stale_jobs(db=db)
    assert n == 0
    assert len(db.fetch_calls) == 1
    sql, args = db.fetch_calls[0]
    s = sql.lower()
    assert "hr_messages" in s
    assert "interview_stages" in s
    assert "scheduled_at" in s
    assert "sent_at" in s
    # больше не голый UPDATE — только SELECT кандидатов, статус меняет add_stage
    assert "update jobs" not in s
    assert args == (
        [FunnelStatus.REJECTED.value, FunnelStatus.ARCHIVE.value, FunnelStatus.OFFER.value],
        21,
    )


@pytest.mark.asyncio
async def test_archive_stale_jobs_routes_each_row_through_add_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Каждая протухшая вакансия переводится в «Отказ» через `add_stage` (не голым SQL) —
    так `application_stages` не расходится с `jobs.status` после авто-архива."""
    db = _FakeSelectDb(
        rows=[
            {"id": 101, "account_id": 1},
            {"id": 102, "account_id": 2},
        ]
    )
    calls: list[tuple[int, str, str, int]] = []

    async def _fake_add_stage(
        job_id: int, stage: str, *, source: str, account_id: int, db: Any = None
    ) -> None:
        calls.append((job_id, stage, source, account_id))

    monkeypatch.setattr(jobs_mod, "add_stage", _fake_add_stage)

    n = await jobs_mod.archive_stale_jobs(db=db)

    assert n == 2
    assert calls == [
        (101, FunnelStatus.REJECTED.value, "stale_ttl", 1),
        (102, FunnelStatus.REJECTED.value, "stale_ttl", 2),
    ]


@pytest.mark.asyncio
async def test_archive_stale_jobs_one_failure_does_not_block_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Best-effort цикл: если `add_stage` упал на одной вакансии, остальные всё равно
    обрабатываются, и счётчик отражает только реально применённые переходы."""
    db = _FakeSelectDb(
        rows=[
            {"id": 201, "account_id": 1},
            {"id": 202, "account_id": 1},
        ]
    )

    async def _flaky_add_stage(
        job_id: int, stage: str, *, source: str, account_id: int, db: Any = None
    ) -> None:
        if job_id == 201:
            raise RuntimeError("boom")

    monkeypatch.setattr(jobs_mod, "add_stage", _flaky_add_stage)

    n = await jobs_mod.archive_stale_jobs(db=db)

    assert n == 1
