"""Расширенное окно контекста для event_extract (МТС «Топ менеджмент», 2026-08-12):
формат/роль этапа мог быть назван на пару сообщений раньше и не повторён в реплике,
подтверждающей дату — единственная последняя реплика теряла этот сигнал.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.pipeline.event_extract import _upsert_stage, recent_hr_context
from core.domains.pipeline.hr_threads import HrMessage
from core.domains.preparation.interview_stages import InterviewStage


def _msg(id_: int, kind: str, body: str) -> HrMessage:
    return HrMessage(id=id_, thread_id=1, kind=kind, body=body)


def test_recent_hr_context_includes_earlier_role_signal() -> None:
    messages = [
        _msg(1, "hr_in", "Направляю слоты для интервью с Руководителем Центра РНД: 18.08 в 12:00"),
        _msg(2, "hr_out", "Отлично, подойдёт 18.08 в 12:00"),
        _msg(3, "hr_in", "Договорились"),
        _msg(4, "hr_in", "Запланировано интервью 18.08 в 12:00, ссылка на встречу..."),
    ]
    context = recent_hr_context(messages, upto_id=4)

    assert "Руководителем Центра РНД" in context
    assert context.strip().endswith("Запланировано интервью 18.08 в 12:00, ссылка на встречу...")
    assert "[HR, последнее]" in context


def test_recent_hr_context_excludes_llm_chatter_and_caps_window() -> None:
    messages = [
        _msg(1, "hr_in", "старое сообщение вне окна"),
        _msg(2, "llm_user", "вопрос ассистенту — не должен попасть в контекст"),
        _msg(3, "llm_assistant", "ответ ассистента — тоже не должен попасть"),
        *[_msg(10 + i, "hr_out", f"реплика {i}") for i in range(6)],
        _msg(20, "hr_in", "финальная реплика HR"),
    ]
    context = recent_hr_context(messages, upto_id=20)

    assert "ассистент" not in context
    assert "старое сообщение вне окна" not in context  # окно = 6, обрезает самые старые
    assert context.strip().endswith("финальная реплика HR")


def test_recent_hr_context_empty_for_no_messages() -> None:
    assert recent_hr_context([], upto_id=None) == ""


@pytest.mark.asyncio
async def test_upsert_stage_defaults_to_hr_screening_for_first_ever_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Вакансия без истории этапов — неясный формат всё ещё безопасно считать первым скринингом."""
    monkeypatch.setattr(
        "core.domains.pipeline.event_extract.load_stages", AsyncMock(return_value=[])
    )
    saved = AsyncMock(side_effect=lambda stage, **_kw: stage.model_copy(update={"id": 1}))
    monkeypatch.setattr("core.domains.pipeline.event_extract.save_stage", saved)
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", AsyncMock(return_value=None)
    )

    from datetime import UTC, datetime

    await _upsert_stage(
        "v1",
        scheduled_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        stage_type="",
        fmt="",
        note="встреча назначена",
        source_message_id=137,
        account_id=7,
        db=AsyncMock(),
    )

    saved.assert_awaited_once()
    assert saved.await_args.args[0].stage_type == "hr_screening"


@pytest.mark.asyncio
async def test_upsert_stage_avoids_hr_screening_default_when_prior_stage_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Скрининг уже пройден — новый неклассифицированный этап не должен снова стать
    "hr_screening" (баг «повторный HR-скрининг», МТС «Топ менеджмент», 2026-08-12)."""
    prior = InterviewStage(
        id=9, vacancy_id="v1", stage_type="hr_screening", status="completed"
    )
    monkeypatch.setattr(
        "core.domains.pipeline.event_extract.load_stages", AsyncMock(return_value=[prior])
    )
    saved = AsyncMock(side_effect=lambda stage, **_kw: stage.model_copy(update={"id": 2}))
    monkeypatch.setattr("core.domains.pipeline.event_extract.save_stage", saved)
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", AsyncMock(return_value=None)
    )

    from datetime import UTC, datetime

    await _upsert_stage(
        "v1",
        scheduled_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        stage_type="",
        fmt="",
        note="интервью назначено",
        source_message_id=137,
        account_id=7,
        db=AsyncMock(),
    )

    saved.assert_awaited_once()
    new_stage = saved.await_args.args[0]
    assert new_stage.stage_type != "hr_screening"
    assert new_stage.stage_type == "manager"


@pytest.mark.asyncio
async def test_upsert_stage_uses_llm_stage_type_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Расширенный контекст дал LLM классифицировать этап — дефолт не подменяет реальный ответ."""
    prior = InterviewStage(
        id=9, vacancy_id="v1", stage_type="hr_screening", status="completed"
    )
    monkeypatch.setattr(
        "core.domains.pipeline.event_extract.load_stages", AsyncMock(return_value=[prior])
    )
    saved = AsyncMock(side_effect=lambda stage, **_kw: stage.model_copy(update={"id": 2}))
    monkeypatch.setattr("core.domains.pipeline.event_extract.save_stage", saved)
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", AsyncMock(return_value=None)
    )

    from datetime import UTC, datetime

    await _upsert_stage(
        "v1",
        scheduled_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        stage_type="manager",
        fmt="",
        note="интервью с руководителем",
        source_message_id=137,
        account_id=7,
        db=AsyncMock(),
    )

    saved.assert_awaited_once()
    assert saved.await_args.args[0].stage_type == "manager"
