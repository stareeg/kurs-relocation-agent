"""A-13: примитив Pipeline — параллелизм, зависимости, частичная деградация."""

from __future__ import annotations

import asyncio

import pytest

from core.app.pipeline import Pipeline, PipelineContext, PipelineError, Step


async def _sleep_value(ctx: PipelineContext, key: str, value: object, delay: float = 0.01):
    await asyncio.sleep(delay)
    return value


@pytest.mark.asyncio
async def test_pipeline_runs_independent_steps_in_parallel():
    started = asyncio.Event()
    finished = asyncio.Event()

    async def a(_ctx: PipelineContext):
        started.set()
        await finished.wait()
        return "a"

    async def b(_ctx: PipelineContext):
        await started.wait()
        finished.set()
        return "b"

    results = await Pipeline([Step("a", a), Step("b", b)], name="par").run()
    assert results == {"a": "a", "b": "b"}


@pytest.mark.asyncio
async def test_pipeline_respects_depends_on_order():
    order: list[str] = []

    async def root(_ctx: PipelineContext):
        order.append("root")
        return 1

    async def child(ctx: PipelineContext):
        order.append("child")
        assert ctx["root"] == 1
        return 2

    results = await Pipeline(
        [
            Step("root", root),
            Step("child", child, depends_on=("root",)),
        ]
    ).run()
    assert order == ["root", "child"]
    assert results == {"root": 1, "child": 2}


@pytest.mark.asyncio
async def test_pipeline_optional_failure_degrades_with_default():
    async def ok(_ctx: PipelineContext):
        return "ok"

    async def boom(_ctx: PipelineContext):
        raise RuntimeError("нет сети")

    results = await Pipeline(
        [
            Step("brief", boom, required=False, default_factory=lambda: "empty"),
            Step("pitch", ok, depends_on=("brief",), required=False),
        ]
    ).run()
    assert results["brief"] == "empty"
    assert results["pitch"] == "ok"


@pytest.mark.asyncio
async def test_pipeline_optional_failure_without_default_emits_error():
    async def boom(_ctx: PipelineContext):
        raise RuntimeError("упал")

    async def ok(_ctx: PipelineContext):
        return "ok"

    events = [
        e
        async for e in Pipeline(
            [
                Step("pitch", boom, required=False),
                Step("questions", ok, required=False),
            ]
        ).stream()
    ]
    types = [(e.type, e.step) for e in events]
    assert ("error", "pitch") in types
    assert ("step_done", "questions") in types
    assert events[-1].type == "done"
    assert events[-1].data["pitch"] is None
    assert events[-1].data["questions"] == "ok"


@pytest.mark.asyncio
async def test_pipeline_required_failure_raises():
    async def boom(_ctx: PipelineContext):
        raise RuntimeError("обязательный")

    with pytest.raises(PipelineError, match="обязательный") as ei:
        await Pipeline([Step("x", boom)]).run()
    assert ei.value.step == "x"
    assert isinstance(ei.value.cause, RuntimeError)


@pytest.mark.asyncio
async def test_pipeline_timeout():
    async def slow(_ctx: PipelineContext):
        await asyncio.sleep(1.0)
        return 1

    with pytest.raises(PipelineError):
        await Pipeline([Step("slow", slow, timeout=0.01)]).run()


@pytest.mark.asyncio
async def test_pipeline_rejects_cycle():
    async def a(_ctx: PipelineContext):
        return 1

    async def b(_ctx: PipelineContext):
        return 2

    with pytest.raises(ValueError, match="цикл"):
        Pipeline(
            [
                Step("a", a, depends_on=("b",)),
                Step("b", b, depends_on=("a",)),
            ]
        )


@pytest.mark.asyncio
async def test_screening_pack_degrades_like_before(monkeypatch: pytest.MonkeyPatch):
    """Контракт скрининг-пакета: brief упал → пустой; один из parallel упал → пакет жив."""
    from core.domains.preparation.screening.brief import JdBrief
    from core.domains.preparation.screening.pack import generate_self_pres_pack
    from core.domains.preparation.screening.pitch import ScreeningPitch
    from core.domains.preparation.screening.style import PitchBlock

    async def fail_brief(**_kw):
        raise RuntimeError("brief down")

    async def ok_pitch(**_kw):
        return ScreeningPitch(
            blocks=[PitchBlock(label="Я", lines=["строка"])],
            why_company="потому",
        )

    async def fail_questions(**_kw):
        raise RuntimeError("questions down")

    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.build_jd_brief", fail_brief
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.generate_screening_pitch", ok_pitch
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.generate_screening_questions",
        fail_questions,
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.publish_screening_pack_ready",
        lambda **_k: None,
    )

    pack = await generate_self_pres_pack(
        account_id=1, vacancy_id="v1", title="Lead", company="X", vacancy_text="текст " * 20
    )
    assert isinstance(pack.jd_brief, JdBrief)
    assert pack.pitch_blocks
    assert pack.hr_questions == []
    assert pack.groups == []


@pytest.mark.asyncio
async def test_screening_pack_both_parallel_fail_raises(monkeypatch: pytest.MonkeyPatch):
    from core.domains.preparation.screening.brief import JdBrief
    from core.domains.preparation.screening.pack import generate_self_pres_pack
    from core.kernel.errors import LlmError

    async def empty_brief(**_kw):
        return JdBrief()

    async def boom(**_kw):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.build_jd_brief", empty_brief
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.generate_screening_pitch", boom
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.generate_screening_questions", boom
    )

    with pytest.raises(LlmError, match="рассказ и вопросы"):
        await generate_self_pres_pack(
            account_id=1, vacancy_id="v1", title="Lead", vacancy_text="текст " * 20
        )


@pytest.mark.asyncio
async def test_screening_pack_events_shape(monkeypatch: pytest.MonkeyPatch):
    from core.domains.preparation.screening.brief import JdBrief
    from core.domains.preparation.screening.pack import generate_self_pres_pack_events
    from core.domains.preparation.screening.pitch import ScreeningPitch
    from core.domains.preparation.screening.questions import (
        HrQuestion,
        ScreeningQuestions,
    )
    from core.domains.preparation.screening.style import PitchBlock

    async def ok_brief(**_kw):
        return JdBrief(role_reality="роль")

    async def ok_pitch(**_kw):
        return ScreeningPitch(blocks=[PitchBlock(label="Я", lines=["a"])], why_company="x")

    async def ok_questions(**_kw):
        return ScreeningQuestions(
            hr_questions=[HrQuestion(question="Q?", draft_answer="A")]
        )

    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.build_jd_brief", ok_brief
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.generate_screening_pitch", ok_pitch
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.generate_screening_questions",
        ok_questions,
    )
    monkeypatch.setattr(
        "core.domains.preparation.screening.pack.publish_screening_pack_ready",
        lambda **_k: None,
    )

    events = [
        e
        async for e in generate_self_pres_pack_events(
            account_id=1, vacancy_id="v1", title="Lead", vacancy_text="текст " * 20
        )
    ]
    types = [e["type"] for e in events]
    assert types[0] == "status" and events[0]["stage"] == "brief"
    assert "brief" in types
    assert "pitch" in types
    assert "questions" in types
    assert types[-1] == "done"
    assert events[-1]["pack"].vacancy_id == "v1"
