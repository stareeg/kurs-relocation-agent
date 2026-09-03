"""`set_funnel_status` должен дозаполнять текст JD на уже существующем stub (Этап 2026-08-18).

Регрессия: владелец открывал реальную страницу вакансии (текст на месте), нажимал
«Откликнуться» — расширение парсило `vacancy_text` из DOM и слало его в POST /funnel, но если
`jobs`-запись уже существовала как пустой stub (skip_stub / синк hh_negotiations-getmatch без
текста), бэк создавал stub только когда вакансии ЕЩЁ НЕ было — свежий текст на существующей
записи молча терялся, и «Отклики» показывали пустую карточку для вакансии, которую владелец
точно открывал и читал.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities import service
from core.domains.opportunities.jobs import Job
from core.kernel.schemas.funnel import FunnelStatus


def _patch_common(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service, "update_apply_fields", AsyncMock())
    # Правка 2026-08-20 (архив/разархив HR-тредов на «Отказ» переехал в подписчика pipeline на
    # ApplicationStageChanged — см. core/domains/pipeline/events.py): `add_stage` мокнут целиком
    # ниже, реального события эти тесты не публикуют, патчить архив/разархив тут больше незачем.
    monkeypatch.setattr(service, "add_stage", AsyncMock())


async def test_backfills_text_on_existing_empty_stub(monkeypatch: pytest.MonkeyPatch):
    stub = Job(
        id=42,
        vacancy_id="136348378",
        vacancy_text="",
        title="Senior Python разработчик",
        company="Бэнкс Софт Системс",
        status=FunnelStatus.VIEWED.value,
        overall_score=None,
        source="hh_negotiations",
    )
    backfill = AsyncMock()
    monkeypatch.setattr(service, "get_job_by_vacancy_id", AsyncMock(return_value=stub))
    monkeypatch.setattr(service, "backfill_vacancy_identity", backfill)
    _patch_common(monkeypatch)

    real_text = "Ищем Senior Python разработчика в команду платежей. " * 5
    status, job_id = await service.set_funnel_status(
        "136348378",
        FunnelStatus.APPLIED.value,
        title="Senior Python разработчик",
        company="Бэнкс Софт Системс",
        vacancy_text=real_text,
        account_id=1,
    )

    assert status == FunnelStatus.APPLIED.value
    assert job_id == 42
    backfill.assert_awaited_once()
    call = backfill.await_args
    assert call.args[0] == 42
    assert call.kwargs["vacancy_text"] == real_text.strip()
    assert call.kwargs["account_id"] == 1


async def test_does_not_backfill_when_no_text_supplied(monkeypatch: pytest.MonkeyPatch):
    """Клик «Откликнуться» на форме доп. вопросов — DOM не вакансийный, текста нет вовсе;
    ничего перезаписывать не должны (падать в пустоту хуже, чем оставить как есть)."""
    stub = Job(
        id=42, vacancy_id="136348378", vacancy_text="", status=FunnelStatus.VIEWED.value
    )
    backfill = AsyncMock()
    monkeypatch.setattr(service, "get_job_by_vacancy_id", AsyncMock(return_value=stub))
    monkeypatch.setattr(service, "backfill_vacancy_identity", backfill)
    _patch_common(monkeypatch)

    await service.set_funnel_status(
        "136348378", FunnelStatus.APPLIED.value, vacancy_text=None, account_id=1
    )

    backfill.assert_not_awaited()


async def test_does_not_backfill_already_scored_job(monkeypatch: pytest.MonkeyPatch):
    """Уже проскоренная вакансия не трогается, даже если каллер зачем-то прислал текст —
    `job_record_needs_vacancy_text` смотрит на overall_score, не только на длину текста."""
    scored = Job(
        id=7,
        vacancy_id="99",
        vacancy_text="x" * 2000,
        overall_score=70,
        status=FunnelStatus.VIEWED.value,
    )
    backfill = AsyncMock()
    monkeypatch.setattr(service, "get_job_by_vacancy_id", AsyncMock(return_value=scored))
    monkeypatch.setattr(service, "backfill_vacancy_identity", backfill)
    _patch_common(monkeypatch)

    await service.set_funnel_status(
        "99", FunnelStatus.APPLIED.value, vacancy_text="какой-то другой текст" * 10, account_id=1
    )

    backfill.assert_not_awaited()


async def test_new_job_still_creates_stub_as_before(monkeypatch: pytest.MonkeyPatch):
    save_job = AsyncMock(return_value=Job(id=1, vacancy_id="55", vacancy_text="текст"))
    monkeypatch.setattr(service, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "save_job", save_job)
    backfill = AsyncMock()
    monkeypatch.setattr(service, "backfill_vacancy_identity", backfill)
    _patch_common(monkeypatch)

    await service.set_funnel_status(
        "55", FunnelStatus.APPLIED.value, vacancy_text="текст", account_id=1
    )

    save_job.assert_awaited_once()
    backfill.assert_not_awaited()
