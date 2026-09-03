"""Этап 6 §6.1 (plans/scoring_precision_2026_08_17.md): backfill `total_responses` из discovery.

hh.ru больше не отдаёт счётчик откликов на странице вакансии (живая проверка 2026-08-18) —
расширение физически не может его достать. SERP (`sources/hh.py`, после фикса кодировки) несёт
его — `run_batch_discovery_stream` при встрече уже известной вакансии теперь доливает пустое
поле, а не просто пропускает строку молча.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities import discovery
from core.domains.opportunities.discovered import DiscoveredVacancy
from core.domains.opportunities.jobs import Job


def _disc(vacancy_id: str = "555", total_responses: int | None = 17) -> DiscoveredVacancy:
    return DiscoveredVacancy(
        vacancy_id=vacancy_id,
        url=f"https://hh.ru/vacancy/{vacancy_id}",
        title="Backend Developer",
        total_responses=total_responses,
    )


@pytest.fixture(autouse=True)
def _patch_discover(monkeypatch):
    async def _fake_discover(*args, **kwargs):
        return [_disc()], 1

    monkeypatch.setattr(discovery, "discover_from_search_url", _fake_discover)


async def test_existing_job_gets_total_responses_backfilled(monkeypatch):
    existing = Job(vacancy_text="уже в базе", vacancy_id="555", total_responses=None)
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", AsyncMock(return_value=existing)
    )
    backfill = AsyncMock()
    monkeypatch.setattr("core.domains.opportunities.jobs.backfill_total_responses", backfill)

    events = [e async for e in discovery.run_batch_discovery_stream("https://hh.ru/search/vacancy?text=x", account_id=1)]

    assert any(e["event"] == "skipped" and e["reason"] == "exists" for e in events)
    backfill.assert_awaited_once_with("555", account_id=1, total_responses=17)


async def test_no_backfill_call_when_discovery_has_no_total_responses(monkeypatch):
    async def _fake_discover_no_data(*args, **kwargs):
        return [_disc(total_responses=None)], 1

    monkeypatch.setattr(discovery, "discover_from_search_url", _fake_discover_no_data)

    existing = Job(vacancy_text="уже в базе", vacancy_id="555", total_responses=None)
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", AsyncMock(return_value=existing)
    )
    backfill = AsyncMock()
    monkeypatch.setattr("core.domains.opportunities.jobs.backfill_total_responses", backfill)

    events = [e async for e in discovery.run_batch_discovery_stream("https://hh.ru/search/vacancy?text=x", account_id=1)]

    assert any(e["event"] == "skipped" for e in events)
    backfill.assert_not_awaited()


async def test_new_vacancy_does_not_trigger_backfill(monkeypatch):
    """Вакансии без существующей записи идут по обычному пути скоринга, не бэкафилла."""
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "core.domains.opportunities.skipped.is_skipped", AsyncMock(return_value=False)
    )
    backfill = AsyncMock()
    monkeypatch.setattr("core.domains.opportunities.jobs.backfill_total_responses", backfill)

    async def _fake_score_and_persist(*args, **kwargs):
        raise RuntimeError("персист не важен для этого теста")

    monkeypatch.setattr(
        "core.domains.opportunities.persist.score_and_persist", _fake_score_and_persist
    )

    events = [e async for e in discovery.run_batch_discovery_stream("https://hh.ru/search/vacancy?text=x", account_id=1)]

    backfill.assert_not_awaited()
    assert any(e["event"] == "error" for e in events)
