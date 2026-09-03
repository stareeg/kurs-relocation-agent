"""_gather_hr_context: расшифровка HR-скрининга — тот же авторитетный источник, что переписка."""

from __future__ import annotations

from datetime import UTC, datetime

from core.domains.opportunities.recalibrate import _gather_hr_context
from core.domains.preparation.debrief import DebriefRecord


def _debrief(**overrides) -> DebriefRecord:
    base = dict(
        id=1,
        vacancy_id="vac-1",
        stage="screening",
        transcript="",
        summary="",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    base.update(overrides)
    return DebriefRecord(**base)


async def _empty_threads(vacancy_id, *, account_id, db=None):
    return []


async def _empty_outcomes(vacancy_id, *, account_id, db=None):
    return []


async def test_gather_hr_context_includes_screening_transcript(
    monkeypatch,
) -> None:
    async def fake_history(vacancy_id, limit=20, *, account_id, db=None):
        return [_debrief(transcript="HR сказал: вилка 500-600к, гибрид 2 дня в офисе")]

    monkeypatch.setattr(
        "core.domains.pipeline.hr_threads.list_threads_by_vacancy", _empty_threads
    )
    monkeypatch.setattr(
        "core.domains.pipeline.stage_outcome.load_stage_outcome_history", _empty_outcomes
    )
    monkeypatch.setattr("core.domains.preparation.debrief.load_debrief_history", fake_history)

    context = await _gather_hr_context("vac-1", job_note=None, account_id=1, db=None)

    assert "Расшифровка HR-скрининга" in context
    assert "вилка 500-600к" in context


async def test_gather_hr_context_falls_back_to_summary_without_transcript(monkeypatch) -> None:
    async def fake_history(vacancy_id, limit=20, *, account_id, db=None):
        return [_debrief(transcript="", summary="HR подтвердил гибрид")]

    monkeypatch.setattr(
        "core.domains.pipeline.hr_threads.list_threads_by_vacancy", _empty_threads
    )
    monkeypatch.setattr(
        "core.domains.pipeline.stage_outcome.load_stage_outcome_history", _empty_outcomes
    )
    monkeypatch.setattr("core.domains.preparation.debrief.load_debrief_history", fake_history)

    context = await _gather_hr_context("vac-1", job_note=None, account_id=1, db=None)

    assert "Итог HR-скрининга" in context
    assert "HR подтвердил гибрид" in context


async def test_gather_hr_context_ignores_non_screening_debriefs(monkeypatch) -> None:
    async def fake_history(vacancy_id, limit=20, *, account_id, db=None):
        return [_debrief(stage="tech", transcript="Разбирали алгоритмы")]

    monkeypatch.setattr(
        "core.domains.pipeline.hr_threads.list_threads_by_vacancy", _empty_threads
    )
    monkeypatch.setattr(
        "core.domains.pipeline.stage_outcome.load_stage_outcome_history", _empty_outcomes
    )
    monkeypatch.setattr("core.domains.preparation.debrief.load_debrief_history", fake_history)

    context = await _gather_hr_context("vac-1", job_note=None, account_id=1, db=None)

    assert context == ""
