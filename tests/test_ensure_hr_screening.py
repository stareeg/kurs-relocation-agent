"""Авто-пометка скрининга при переходе в Техничку (ensure_hr_screening_completed) и авто-открытие
строки HR-скрининга при переходе в Скрининг (ensure_hr_screening_stage_open)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.domains.preparation.events import on_application_stage_changed
from core.domains.preparation.interview_stages import (
    InterviewStage,
    ensure_hr_screening_completed,
    ensure_hr_screening_stage_open,
)
from core.kernel.events import ApplicationStageChanged
from core.kernel.ids import VacancyId


@pytest.mark.asyncio
async def test_completes_open_hr_screening(monkeypatch: pytest.MonkeyPatch) -> None:
    stages = [
        InterviewStage(id=11, vacancy_id="v1", stage_type="hr_screening", status="scheduled"),
        InterviewStage(id=12, vacancy_id="v1", stage_type="live_coding", status="scheduled"),
    ]
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.load_stages",
        AsyncMock(return_value=stages),
    )
    complete = AsyncMock(return_value=stages[0].model_copy(update={"status": "completed"}))
    monkeypatch.setattr("core.domains.preparation.interview_stages.complete_stage_by_id", complete)

    db = MagicMock()
    await ensure_hr_screening_completed("v1", account_id=7, db=db)

    complete.assert_awaited_once()
    assert complete.await_args.args[0] == 11
    assert complete.await_args.kwargs.get("account_id") == 7
    assert complete.await_args.kwargs.get("db") is db


@pytest.mark.asyncio
async def test_skips_already_completed_screening(monkeypatch: pytest.MonkeyPatch) -> None:
    stages = [
        InterviewStage(id=11, vacancy_id="v1", stage_type="hr_screening", status="completed"),
    ]
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.load_stages",
        AsyncMock(return_value=stages),
    )
    complete = AsyncMock()
    monkeypatch.setattr("core.domains.preparation.interview_stages.complete_stage_by_id", complete)
    db = AsyncMock()

    await ensure_hr_screening_completed("v1", account_id=7, db=db)

    complete.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_creates_completed_screening_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.load_stages",
        AsyncMock(return_value=[]),
    )
    complete = AsyncMock()
    monkeypatch.setattr("core.domains.preparation.interview_stages.complete_stage_by_id", complete)
    db = AsyncMock()

    await ensure_hr_screening_completed("v1", account_id=7, db=db)

    complete.assert_not_awaited()
    assert db.execute.await_count == 2
    bump_sql = db.execute.await_args_list[0].args[0]
    insert_sql = db.execute.await_args_list[1].args[0]
    assert "position = position + 1" in bump_sql
    assert "hr_screening" in insert_sql
    assert "completed" in insert_sql


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["Техничка", "Финал", "Оффер"])
async def test_ensures_screening_for_every_stage_after_screening(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """Вакансия может прыгнуть из «Скрининга» сразу в «Финал»/«Оффер» — строка скрининга нужна
    и там, иначе в цепочке Техничек этапа HR-скрининга просто нет."""
    ensure = AsyncMock()
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_completed", ensure
    )

    await on_application_stage_changed(
        ApplicationStageChanged(vacancy_id=VacancyId("v1"), stage=stage, account_id=7)
    )

    ensure.assert_awaited_once_with("v1", account_id=7)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["Просмотр", "Отклик", "Скрининг", "Отказ"])
async def test_skips_stages_before_screening_is_done(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    ensure = AsyncMock()
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_completed", ensure
    )

    await on_application_stage_changed(
        ApplicationStageChanged(vacancy_id=VacancyId("v1"), stage=stage)
    )

    ensure.assert_not_awaited()


@pytest.mark.asyncio
async def test_opens_hr_screening_stage_on_screening_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Переход в «Скрининг» ⇒ строка HR-скрининга должна появиться открытой, не пройденной —
    иначе в дровере цепочка стоит пустой до тех пор, пока вакансия не проедет мимо скрининга."""
    open_screening = AsyncMock()
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_stage_open",
        open_screening,
    )
    complete = AsyncMock()
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_completed", complete
    )

    await on_application_stage_changed(
        ApplicationStageChanged(vacancy_id=VacancyId("v1"), stage="Скрининг", account_id=7)
    )

    open_screening.assert_awaited_once_with("v1", account_id=7)
    complete.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["Просмотр", "Отклик", "Техничка", "Финал", "Оффер", "Отказ"])
async def test_does_not_open_screening_stage_for_other_transitions(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    open_screening = AsyncMock()
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_stage_open",
        open_screening,
    )
    # Техничка/Финал/Оффер реально зовут ensure_hr_screening_completed — глушим и её, иначе
    # тест бьёт по настоящей БД в ветках, которые здесь не проверяем.
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.ensure_hr_screening_completed", AsyncMock()
    )

    await on_application_stage_changed(
        ApplicationStageChanged(vacancy_id=VacancyId("v1"), stage=stage, account_id=7)
    )

    open_screening.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_hr_screening_stage_open_noop_when_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages = [InterviewStage(id=11, vacancy_id="v1", stage_type="hr_screening", status="completed")]
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.load_stages",
        AsyncMock(return_value=stages),
    )
    db = AsyncMock()

    await ensure_hr_screening_stage_open("v1", account_id=7, db=db)

    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_hr_screening_stage_open_inserts_scheduled_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.load_stages",
        AsyncMock(return_value=[]),
    )
    db = AsyncMock()

    await ensure_hr_screening_stage_open("v1", account_id=7, db=db)

    assert db.execute.await_count == 2
    bump_sql = db.execute.await_args_list[0].args[0]
    insert_sql = db.execute.await_args_list[1].args[0]
    assert "position = position + 1" in bump_sql
    assert "hr_screening" in insert_sql
    assert "scheduled" in insert_sql
