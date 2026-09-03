"""Регресс §16 плана local_context_blind_spots_2026_08_12.md: `_sync_one` раньше не логировал
ничего в ветке `if not guard_ok:` — причина блокировки уходила только в HTTP-ответ
(`NegotiationSyncResultItem.reason`), разовый тост фронта, нигде не сохраняется. Именно из-за
этого баг «ТехВилл» (job 317, 2026-08-12) нельзя было продиагностировать без прямого SSH+psql к
проду. Теперь ветка обязана оставить строку в `copilot_logs` (через `event()`, INFO)."""

from __future__ import annotations

import logging

import pytest

from core.config import get_settings
from core.domains.offers.hh_negotiations import NegotiationSyncItem
from core.domains.opportunities.jobs import Job
from core.domains.pipeline.negotiations import _sync_one
from core.kernel.schemas.funnel import FunnelStatus


@pytest.mark.asyncio
async def test_guard_block_emits_event_log(caplog: pytest.LogCaptureFixture) -> None:
    """HH присылает «Отказ» на вакансию, уже стоящую на «Скрининге» — защита воронки блокирует
    понижение (job 317 сценарий). Ветка должна залогировать `vacancy_id`/`current`/`proposed`."""
    item = NegotiationSyncItem(
        vacancy_id="135719770",
        hh_status_raw="Отказ",
        company="ТехВилл",
        title="Техлид Дата Сайентист",
    )
    job = Job(
        id=317,
        vacancy_id="135719770",
        vacancy_text="",
        status=FunnelStatus.SCREENING.value,
    )

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.negotiations"):
        result = await _sync_one(
            item,
            dry_run=True,
            use_llm=False,
            force=False,
            settings=get_settings(),
            job=job,
            account_id=1,
        )

    assert result.applied is False
    assert result.skipped is True

    blocked_records = [r for r in caplog.records if getattr(r, "event", None) == "ЗАДАЧА"]
    assert blocked_records, "ветка `if not guard_ok:` должна логировать событие"
    record = blocked_records[0]
    assert record.vacancy_id == "135719770"
    assert record.current == FunnelStatus.SCREENING.value
    assert record.proposed == FunnelStatus.REJECTED.value


@pytest.mark.asyncio
async def test_no_block_no_event(caplog: pytest.LogCaptureFixture) -> None:
    """Симметричная проверка: когда защита НЕ срабатывает (обновление применяется), ветка
    блокировки не должна оставлять ложный лог."""
    item = NegotiationSyncItem(
        vacancy_id="135719771",
        hh_status_raw="Приглашение на собеседование",
        company="Other Co",
        title="Backend",
    )
    job = Job(
        id=318,
        vacancy_id="135719771",
        vacancy_text="",
        status=FunnelStatus.APPLIED.value,
    )

    with caplog.at_level(logging.INFO, logger="core.domains.pipeline.negotiations"):
        result = await _sync_one(
            item,
            dry_run=True,
            use_llm=False,
            force=False,
            settings=get_settings(),
            job=job,
            account_id=1,
        )

    assert result.applied is True
    blocked_records = [r for r in caplog.records if getattr(r, "event", None) == "ЗАДАЧА"]
    assert not blocked_records
