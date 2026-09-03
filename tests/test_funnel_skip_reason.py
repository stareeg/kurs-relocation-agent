"""`get_funnel_snapshot` (backing `GET /funnel/{vacancy_id}`) должен отдавать причину пропуска
вместе с флагом `skipped`.

Раньше endpoint возвращал только `is_skipped()` (bool) — расширение переживало факт пропуска
после перезагрузки страницы/новой вкладки (skippedCache), но не причину (skipReasonCache
никогда не гидрировался с бэкенда), и done-state «Пропущено» показывался без пояснения.
"""

from __future__ import annotations

import pytest

from core.domains.opportunities.jobs import Job
from core.domains.opportunities.service import get_funnel_snapshot
from core.domains.opportunities.skipped import SkippedVacancy


@pytest.mark.asyncio
async def test_snapshot_returns_canonical_skip_reason(monkeypatch):
    async def fake_get_job(vacancy_id, *, account_id):
        return None

    async def fake_get_skipped(vacancy_id, *, account_id):
        return SkippedVacancy(
            vacancy_id=vacancy_id,
            skip_reason="Избегать компанию",
            canonical_reason="Избегать компанию",
        )

    monkeypatch.setattr(
        "core.domains.opportunities.service.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr("core.domains.opportunities.service.get_skipped", fake_get_skipped)

    snapshot = await get_funnel_snapshot("123", account_id=7)

    assert snapshot.skipped is True
    assert snapshot.skip_reason == "Избегать компанию"


@pytest.mark.asyncio
async def test_snapshot_derives_canonical_reason_for_legacy_rows(monkeypatch):
    """Старые записи без `canonical_reason` (до миграции 0100) — канон выводим на лету."""

    async def fake_get_job(vacancy_id, *, account_id):
        return None

    async def fake_get_skipped(vacancy_id, *, account_id):
        return SkippedVacancy(
            vacancy_id=vacancy_id, skip_reason="Сомнительная компания", canonical_reason=None
        )

    monkeypatch.setattr(
        "core.domains.opportunities.service.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr("core.domains.opportunities.service.get_skipped", fake_get_skipped)

    snapshot = await get_funnel_snapshot("123", account_id=7)

    assert snapshot.skipped is True
    assert snapshot.skip_reason == "Избегать компанию"


@pytest.mark.asyncio
async def test_snapshot_no_skip_reason_when_not_skipped(monkeypatch):
    async def fake_get_job(vacancy_id, *, account_id):
        return Job(vacancy_id=vacancy_id, vacancy_text="текст", status="Просмотрено")

    async def fake_get_skipped(vacancy_id, *, account_id):
        return None

    monkeypatch.setattr(
        "core.domains.opportunities.service.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr("core.domains.opportunities.service.get_skipped", fake_get_skipped)

    snapshot = await get_funnel_snapshot("123", account_id=7)

    assert snapshot.skipped is False
    assert snapshot.skip_reason is None
    assert snapshot.status == "Просмотрено"
