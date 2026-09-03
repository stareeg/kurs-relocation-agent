"""Извлечение следующего этапа из расшифровки HR-скрининга (хвост разбора, _tails)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import core.domains.preparation.interview.next_stage as next_stage_mod
from core.domains.preparation.interview.next_stage import (
    NextStageHint,
    apply_next_stage_safe,
    extract_next_stage,
)
from core.domains.preparation.interview_stages import InterviewStage
from core.kernel import ports
from tests.fakes import FakeLlm, RaisingLlm


async def test_extract_next_stage_short_transcript_skips_llm() -> None:
    with ports.use_ports(llm=RaisingLlm()):
        hint = await extract_next_stage("коротко")
    assert hint == NextStageHint()


async def test_extract_next_stage_returns_llm_result() -> None:
    expected = NextStageHint(
        mentioned=True,
        stage_type="live_coding",
        format="online",
        notes="техничка на следующей неделе",
    )
    llm = FakeLlm(result=expected)
    with ports.use_ports(llm=llm):
        hint = await extract_next_stage("HR: на следующей неделе позовём на техничку " * 3)
    assert hint == expected
    assert llm.features == ["next_stage_hint"]


async def test_apply_next_stage_safe_noop_when_not_mentioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = FakeLlm(result=NextStageHint(mentioned=False))

    async def _no_call(*_args, **_kwargs):
        raise AssertionError("save_stage не должен вызываться — mentioned=False")

    monkeypatch.setattr(next_stage_mod, "save_stage", _no_call)

    with ports.use_ports(llm=llm):
        await apply_next_stage_safe("vac-1", "переписка про зарплату " * 5, account_id=1)


async def test_apply_next_stage_safe_saves_stage_when_mentioned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future = datetime.now(UTC) + timedelta(days=7)
    llm = FakeLlm(
        result=NextStageHint(
            mentioned=True,
            stage_type="live_coding",
            scheduled_at=future,
            format="online",
            notes="через неделю техничка",
        )
    )

    saved: list[InterviewStage] = []

    async def fake_save_stage(stage: InterviewStage, *, account_id: int, db=None):
        saved.append(stage)
        return stage.model_copy(update={"id": 1})

    monkeypatch.setattr(next_stage_mod, "save_stage", fake_save_stage)

    with ports.use_ports(llm=llm):
        await apply_next_stage_safe("vac-1", "HR: техничка через неделю " * 5, account_id=1)

    assert len(saved) == 1
    stage = saved[0]
    assert stage.vacancy_id == "vac-1"
    assert stage.stage_type == "live_coding"
    assert stage.format == "online"
    assert stage.status == "scheduled"  # дата в будущем
    assert stage.notes == "через неделю техничка"


async def test_apply_next_stage_safe_marks_past_date_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    past = datetime.now(UTC) - timedelta(days=3)
    llm = FakeLlm(
        result=NextStageHint(mentioned=True, stage_type="final", scheduled_at=past)
    )

    saved: list[InterviewStage] = []

    async def fake_save_stage(stage: InterviewStage, *, account_id: int, db=None):
        saved.append(stage)
        return stage

    monkeypatch.setattr(next_stage_mod, "save_stage", fake_save_stage)

    with ports.use_ports(llm=llm):
        await apply_next_stage_safe("vac-1", "HR: финал был во вторник " * 5, account_id=1)

    assert saved[0].status == "completed"
