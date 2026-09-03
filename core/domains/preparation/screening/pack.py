"""Оркестрация пакета самопрезентации под вакансию (→ Pipeline).

Разбор вакансии (`brief`) → параллельно рассказ (`pitch`) и вопросы (`questions`).
Частичная деградация: упал brief → пустой JdBrief; упал один из параллельных → пакет
с тем, что собралось; упали оба → `LlmError`. Стрим событий для UI сохранён
(`status` / `brief` / `pitch` / `questions` / `part_error` / `done`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from core.app.pipeline import Pipeline, PipelineContext, Step
from core.domains.preparation.events import publish_screening_pack_ready
from core.domains.preparation.screening.brief import JdBrief, build_jd_brief
from core.domains.preparation.screening.pitch import (
    ScreeningPitch,
    generate_screening_pitch,
    pitch_to_plain_text,
)
from core.domains.preparation.screening.questions import (
    HrQuestion,
    QuestionGroup,
    ScreeningQuestions,
    generate_screening_questions,
)
from core.domains.preparation.screening.style import PitchBlock
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)


class VacancySelfPres(BaseModel):
    """Канонический пакет подготовки к скринингу: разбор + рассказ + вопросы."""

    vacancy_id: str = ""
    jd_brief: JdBrief = Field(default_factory=JdBrief)
    pitch_blocks: list[PitchBlock] = Field(default_factory=list)
    oral_pitch: str = ""
    why_company: str = ""
    hr_questions: list[HrQuestion] = Field(default_factory=list)
    groups: list[QuestionGroup] = Field(default_factory=list)
    input_hash: str = ""


def _pack_pipeline() -> Pipeline:
    """DAG скрининг-пакета: brief → (pitch ∥ questions)."""

    async def brief_step(ctx: PipelineContext) -> JdBrief:
        return await build_jd_brief(
            title=ctx.get("title", ""),
            company=ctx.get("company", ""),
            vacancy_text=ctx.get("vacancy_text", ""),
            score_summary=ctx.get("score_summary", ""),
        )

    async def pitch_step(ctx: PipelineContext) -> ScreeningPitch:
        brief = ctx.get("brief") or JdBrief()
        return await generate_screening_pitch(
            account_id=ctx["account_id"],
            brief=brief,
            title=ctx.get("title", ""),
            company=ctx.get("company", ""),
            score_summary=ctx.get("score_summary", ""),
        )

    async def questions_step(ctx: PipelineContext) -> ScreeningQuestions:
        brief = ctx.get("brief") or JdBrief()
        return await generate_screening_questions(
            account_id=ctx["account_id"],
            brief=brief,
            title=ctx.get("title", ""),
            company=ctx.get("company", ""),
            score_summary=ctx.get("score_summary", ""),
        )

    return Pipeline(
        [
            Step("brief", brief_step, required=False, default_factory=JdBrief),
            Step("pitch", pitch_step, depends_on=("brief",), required=False),
            Step("questions", questions_step, depends_on=("brief",), required=False),
        ],
        name="self_pres_pack",
    )


def _assemble(
    *,
    vacancy_id: str,
    brief: JdBrief,
    pitch: ScreeningPitch | None,
    questions: ScreeningQuestions | None,
    company: str,
) -> VacancySelfPres:
    if pitch is None and questions is None:
        raise LlmError("рассказ и вопросы не собрались")
    pack = VacancySelfPres(
        vacancy_id=vacancy_id,
        jd_brief=brief,
        pitch_blocks=list(pitch.blocks) if pitch else [],
        oral_pitch=pitch_to_plain_text(pitch.blocks) if pitch else "",
        why_company=pitch.why_company if pitch else "",
        hr_questions=list(questions.hr_questions) if questions else [],
        groups=list(questions.groups) if questions else [],
    )
    if not pack.pitch_blocks and not pack.hr_questions and not pack.groups:
        raise ValueError("LLM вернул пустой пакет самопрезентации")
    degraded = [name for name, part in (("pitch", pitch), ("questions", questions)) if part is None]
    event(
        logger,
        "LLM",
        "screening pack собран: питч=%d блоков, вопросов HR=%d, групп=%d, деградация=%s",
        len(pack.pitch_blocks),
        len(pack.hr_questions),
        len(pack.groups),
        degraded or "нет",
        vacancy_id=pack.vacancy_id,
        pitch_blocks=len(pack.pitch_blocks),
        hr_questions=len(pack.hr_questions),
        groups=len(pack.groups),
        degraded_steps=degraded,
        level=logging.WARNING if degraded else logging.INFO,
    )
    _publish_ready(pack, company)
    return pack


def _publish_ready(pack: VacancySelfPres, company: str) -> None:
    """A-11: пакет собран (возможно, частично) — содержимое подписчик возьмёт сам."""
    publish_screening_pack_ready(
        vacancy_id=pack.vacancy_id,
        company=company,
        pitch_blocks=len(pack.pitch_blocks),
        hr_questions=len(pack.hr_questions),
    )


async def generate_self_pres_pack(
    *,
    account_id: int,
    vacancy_id: str = "",
    title: str = "",
    company: str = "",
    vacancy_text: str = "",
    score_summary: str = "",
) -> VacancySelfPres:
    """Вакансия → разбор → параллельно рассказ + вопросы, один канонический пакет."""
    if not (vacancy_text or "").strip() and not (title or "").strip():
        raise ValueError("нет текста вакансии - выберите вакансию с описанием")

    results = await _pack_pipeline().run(
        account_id=account_id,
        title=title,
        company=company,
        vacancy_text=vacancy_text,
        score_summary=score_summary,
    )
    brief = results.get("brief") or JdBrief()
    pitch = results.get("pitch")
    questions = results.get("questions")
    if pitch is not None and not isinstance(pitch, ScreeningPitch):
        pitch = None
    if questions is not None and not isinstance(questions, ScreeningQuestions):
        questions = None
    return _assemble(
        vacancy_id=vacancy_id,
        brief=brief if isinstance(brief, JdBrief) else JdBrief(),
        pitch=pitch,
        questions=questions,
        company=company,
    )


async def generate_self_pres_pack_events(
    *,
    account_id: int,
    vacancy_id: str = "",
    title: str = "",
    company: str = "",
    vacancy_text: str = "",
    score_summary: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Тот же пайплайн, но отдаёт события по мере готовности частей (прогрессивный UI)."""
    if not (vacancy_text or "").strip() and not (title or "").strip():
        raise ValueError("нет текста вакансии - выберите вакансию с описанием")

    brief = JdBrief()
    pitch: ScreeningPitch | None = None
    questions: ScreeningQuestions | None = None
    parallel_status_sent = False

    async for pipeline_event in _pack_pipeline().stream(
        account_id=account_id,
        title=title,
        company=company,
        vacancy_text=vacancy_text,
        score_summary=score_summary,
    ):
        if pipeline_event.type == "step_start" and pipeline_event.step == "brief":
            yield {"type": "status", "stage": "brief", "label": "Разбираю вакансию"}
        elif pipeline_event.type == "step_start" and pipeline_event.step in ("pitch", "questions"):
            if not parallel_status_sent:
                parallel_status_sent = True
                yield {"type": "status", "stage": "parallel", "label": "Пишу легенду и вопросы"}
        elif pipeline_event.type == "step_done" and pipeline_event.step == "brief":
            brief = pipeline_event.data if isinstance(pipeline_event.data, JdBrief) else JdBrief()
            yield {"type": "brief", "jd_brief": brief.model_dump(mode="json")}
        elif pipeline_event.type == "step_done" and pipeline_event.step == "pitch":
            if not isinstance(pipeline_event.data, ScreeningPitch):
                raise TypeError(f"ожидался ScreeningPitch, получено {type(pipeline_event.data)!r}")
            pitch = pipeline_event.data
            yield {
                "type": "pitch",
                "pitch_blocks": [b.model_dump(mode="json") for b in pitch.blocks],
                "oral_pitch": pitch_to_plain_text(pitch.blocks),
                "why_company": pitch.why_company,
            }
        elif pipeline_event.type == "step_done" and pipeline_event.step == "questions":
            if not isinstance(pipeline_event.data, ScreeningQuestions):
                raise TypeError(
                    f"ожидался ScreeningQuestions, получено {type(pipeline_event.data)!r}"
                )
            questions = pipeline_event.data
            yield {
                "type": "questions",
                "hr_questions": [q.model_dump(mode="json") for q in questions.hr_questions],
                "groups": [g.model_dump(mode="json") for g in questions.groups],
            }
        elif pipeline_event.type == "error" and pipeline_event.step in ("pitch", "questions"):
            yield {
                "type": "part_error",
                "stage": pipeline_event.step,
                "message": pipeline_event.message,
            }
        elif pipeline_event.type == "done":
            pack = _assemble(
                vacancy_id=vacancy_id,
                brief=brief,
                pitch=pitch,
                questions=questions,
                company=company,
            )
            yield {"type": "done", "pack": pack}


__all__ = ["VacancySelfPres", "generate_self_pres_pack", "generate_self_pres_pack_events"]
