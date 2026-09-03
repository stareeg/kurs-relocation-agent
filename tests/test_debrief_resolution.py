"""DBR-5: жизненный цикл сигнала разбора (pending → advanced/rejected по факту переписки с HR)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import core.domains.preparation.interview.debrief_resolution as resolution_mod
from core.domains.preparation.interview.debrief_resolution import (
    _ResolutionVerdict,
    resolve_pending_debrief_signal,
)
from core.domains.preparation.debrief import DebriefRecord
from core.domains.pipeline.hr_threads import HrMessage, HrThread
from core.kernel import ports
from tests.fakes import FakeLlm, RaisingLlm


def _debrief(**overrides) -> DebriefRecord:
    base = dict(
        id=1,
        vacancy_id="vac-1",
        stage="tech",
        analysis={"summary": "ok", "topics_to_study": ["SQL"]},
        interview_stage_id=42,
        resolution="pending",
        created_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return DebriefRecord(**base)


async def _no_call(*_args, **_kwargs):
    raise AssertionError("не должно быть вызвано — сигнал резолвится раньше по данным")


async def test_no_pending_debrief_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(vacancy_id, *, account_id, db=None):
        return None

    monkeypatch.setattr(resolution_mod, "load_latest_pending_debrief", fake_load)
    monkeypatch.setattr("core.domains.pipeline.hr_threads.get_primary_thread", _no_call)

    with ports.use_ports(llm=RaisingLlm()):
        result = await resolve_pending_debrief_signal("vac-1", account_id=1)
    assert result is None


async def test_no_new_hr_in_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    debrief = _debrief()

    async def fake_load(vacancy_id, *, account_id, db=None):
        return debrief

    async def fake_thread(vacancy_id, *, account_id, db=None):
        return HrThread(id=1, vacancy_id=vacancy_id)

    async def fake_messages(thread_id, *, account_id, db=None):
        # реплика ДО created_at разбора — не новая, резолвить нечего.
        return [
            HrMessage(
                thread_id=1, kind="hr_in", body="до разбора",
                sent_at=debrief.created_at - timedelta(days=1),
            )
        ]

    monkeypatch.setattr(resolution_mod, "load_latest_pending_debrief", fake_load)
    monkeypatch.setattr("core.domains.pipeline.hr_threads.get_primary_thread", fake_thread)
    monkeypatch.setattr("core.domains.pipeline.hr_threads.list_messages", fake_messages)

    with ports.use_ports(llm=RaisingLlm()):
        result = await resolve_pending_debrief_signal("vac-1", account_id=1)
    assert result is None


async def _setup_new_hr_in(monkeypatch: pytest.MonkeyPatch, debrief: DebriefRecord):
    async def fake_load(vacancy_id, *, account_id, db=None):
        return debrief

    async def fake_thread(vacancy_id, *, account_id, db=None):
        return HrThread(id=1, vacancy_id=vacancy_id)

    async def fake_messages(thread_id, *, account_id, db=None):
        return [
            HrMessage(
                thread_id=1, kind="hr_in", body="новое сообщение HR",
                sent_at=debrief.created_at + timedelta(days=1),
            )
        ]

    monkeypatch.setattr(resolution_mod, "load_latest_pending_debrief", fake_load)
    monkeypatch.setattr("core.domains.pipeline.hr_threads.get_primary_thread", fake_thread)
    monkeypatch.setattr("core.domains.pipeline.hr_threads.list_messages", fake_messages)


async def test_pending_verdict_leaves_debrief_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    debrief = _debrief()
    await _setup_new_hr_in(monkeypatch, debrief)

    llm = FakeLlm(result=_ResolutionVerdict(resolution="pending", note="пока неясно"))

    monkeypatch.setattr(resolution_mod, "mark_debrief_resolution", _no_call)

    with ports.use_ports(llm=llm):
        result = await resolve_pending_debrief_signal("vac-1", account_id=1)
    assert result is None


async def test_advanced_updates_resolution_only(monkeypatch: pytest.MonkeyPatch) -> None:
    debrief = _debrief()
    await _setup_new_hr_in(monkeypatch, debrief)

    llm = FakeLlm(result=_ResolutionVerdict(resolution="advanced", note="назначили финал"))

    marked = {}

    async def fake_mark(debrief_id, resolution, note="", *, account_id, db=None):
        marked["args"] = (debrief_id, resolution, note)
        return debrief.model_copy(update={"resolution": resolution, "resolved_note": note})

    monkeypatch.setattr(resolution_mod, "mark_debrief_resolution", fake_mark)
    monkeypatch.setattr(resolution_mod, "_apply_auto_reject", _no_call)

    with ports.use_ports(llm=llm):
        result = await resolve_pending_debrief_signal("vac-1", account_id=1)
    assert marked["args"] == (1, "advanced", "назначили финал")
    assert result is not None
    assert result.resolution == "advanced"


async def test_rejected_marks_stage_failed_and_rejects_job_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debrief = _debrief()
    await _setup_new_hr_in(monkeypatch, debrief)

    llm = FakeLlm(result=_ResolutionVerdict(resolution="rejected", note="выбрали другого кандидата"))

    async def fake_mark(debrief_id, resolution, note="", *, account_id, db=None):
        return debrief.model_copy(update={"resolution": resolution, "resolved_note": note})

    monkeypatch.setattr(resolution_mod, "mark_debrief_resolution", fake_mark)

    failed_stage_ids = []
    add_stage_calls = []
    outcome_calls = []

    async def fake_fail_stage(stage_id, *, account_id, db=None):
        failed_stage_ids.append(stage_id)

    async def fake_get_job(vacancy_id, *, account_id, db=None):
        class Job:
            id = 7
            status = "Техничка"

        return Job()

    async def fake_add_stage(job_id, stage, *, source="manual", account_id, db=None):
        add_stage_calls.append((job_id, stage, source))

    async def fake_save_stage_outcome(record, *, account_id, db=None):
        outcome_calls.append(record)
        return record

    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.fail_stage", fake_fail_stage
    )
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr("core.domains.opportunities.jobs.add_stage", fake_add_stage)
    monkeypatch.setattr("core.domains.pipeline.stage_outcome.save_stage_outcome", fake_save_stage_outcome)

    with ports.use_ports(llm=llm):
        result = await resolve_pending_debrief_signal("vac-1", account_id=1)

    assert result is not None
    assert result.resolution == "rejected"
    assert failed_stage_ids == [42]
    assert add_stage_calls == [(7, "Отказ", "debrief_auto_reject")]
    assert len(outcome_calls) == 1
    assert outcome_calls[0].outcome == "rejected"
    assert "Не прошёл техничку" in outcome_calls[0].recruiter_feedback


async def test_rejected_is_idempotent_when_job_already_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторный резолв (гонка фоновых задач) не должен второй раз двигать уже отказанную вакансию."""
    debrief = _debrief()

    add_stage_calls = []

    async def fake_get_job(vacancy_id, *, account_id, db=None):
        class Job:
            id = 7
            status = "Отказ"

        return Job()

    async def fake_add_stage(job_id, stage, *, source="manual", account_id, db=None):
        add_stage_calls.append((job_id, stage, source))

    async def fake_fail_stage(stage_id, *, account_id, db=None):
        pass

    async def fake_save_stage_outcome(record, *, account_id, db=None):
        return record

    monkeypatch.setattr(
        "core.domains.preparation.interview_stages.fail_stage", fake_fail_stage
    )
    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr("core.domains.opportunities.jobs.add_stage", fake_add_stage)
    monkeypatch.setattr("core.domains.pipeline.stage_outcome.save_stage_outcome", fake_save_stage_outcome)

    await resolution_mod._apply_auto_reject("vac-1", debrief, "note", account_id=1, db=None)

    assert add_stage_calls == []
