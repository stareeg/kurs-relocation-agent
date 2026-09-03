"""Проекции домена preparation в транспортные схемы.

Роутеры подготовки почти целиком состояли из такой раскладки: доменная модель → Pydantic-схема
API. Здесь она собрана в одном месте, чтобы обработчик остался в 15 строках.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from api.schemas import (
    DebriefHistory,
    DebriefResult,
    HrQuestion,
    InterviewStageListResponse,
    InterviewStageOut,
    PitchBlock,
    PrepChatMessageOut,
    PrepChatResponse,
    PrepCompanyProfile,
    PrepQuestionOut,
    PrepResult,
    PrepSobesContextResponse,
    PrepTopicOut,
    PrepTopicsResponse,
    QuestionGroup,
    SavedScreeningQuestions,
    ScreeningQuestion,
)
from api.schemas.attachments import attachment_meta_out
from core.app.scenarios.debrief import DebriefResult as DebriefScenarioResult
from core.app.scenarios.prep_chat import PrepChatReply
from core.domains.assistant.attachments.models import AttachmentMeta
from core.domains.preparation.interview.company_profiles import CompanyProfile
from core.domains.preparation.interview_stages import InterviewStage
from core.domains.preparation.models import (
    INTERVIEW_FORMAT_LABELS,
    SIGNAL_LABELS_WEB,
    STAGE_LABELS,
    STAGE_TYPE_LABELS,
    DebriefAnalysis,
    PrepQuestion,
    PrepStage,
)
from core.domains.preparation.scenarios import (
    PrepView,
    SobesOverlay,
    VacancyRef,
)
from core.kernel.text import wrap_untrusted

#: Поля карточки вакансии, которые фронт шлёт почти в каждом теле запроса подготовки.
_REF_FIELDS = ("vacancy_text", "title", "company", "salary_text", "score")


def vacancy_ref(vacancy_id: str, body: Any) -> VacancyRef:
    """Тело запроса → доменная карточка вакансии; чего нет в схеме — берём дефолт."""
    values = {f: getattr(body, f, None) for f in _REF_FIELDS}
    return VacancyRef(vacancy_id=vacancy_id, **{k: v for k, v in values.items() if v is not None})


def prep_chat_llm_history(items: Sequence[PrepChatMessageOut]) -> list[dict[str, str]]:
    """История чата → role/content для LLM (Э3-3, план chat_image_attachments).

    Картинки ПРОШЛЫХ реплик уходят в промпт текстом (`analysis.title`/`.text`), не пикселями —
    инлайном в модель попадают только вложения текущей реплики (`_load_current_images` в
    `core.app.scenarios.prep_chat`, §3 плана). Ещё не распознанные/упавшие вложения молча
    пропускаются — на текст истории они не влияют.
    """
    out: list[dict[str, str]] = []
    for m in items:
        parts = [m.content] if m.content.strip() else []
        for att in m.attachments:
            if att.analysis_status != "ready" or att.analysis is None:
                continue
            title = att.analysis.title.strip() or "Скриншот"
            text = att.analysis.text.strip()
            line = f"[{title}]"
            if text:
                line += f": {wrap_untrusted(text, source='attachment')}"
            parts.append(line)
        out.append({"role": m.role, "content": "\n".join(parts)})
    return out


# --------------------------------------------------------------------------- подготовка


def prep_question_out(q: PrepQuestion) -> PrepQuestionOut:
    return PrepQuestionOut(
        category=q.category,
        text=q.text,
        hint=q.hint,
        answer=q.answer,
        outcome=q.outcome,
        mastery=q.mastery,
        topic=q.topic,
    )


def company_profile_out(profile: CompanyProfile | None) -> PrepCompanyProfile | None:
    if profile is None:
        return None
    return PrepCompanyProfile(key=profile.key, name=profile.name, summary=profile.summary)


def prep_result(view: PrepView) -> PrepResult:
    return PrepResult(
        vacancy_id=view.vacancy_id,
        stage=view.stage,
        stage_label=STAGE_LABELS.get(view.stage, view.stage),
        questions=[prep_question_out(q) for q in view.questions],
        checklist=view.checklist,
        framework=view.framework,
        generated_at=view.generated_at,
        source=view.source,
        company_profile=company_profile_out(view.company_profile),
    )


async def prep_sse_payloads(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Доменные события сборки подготовки → payload'ы единого SSE."""
    async for event in events:
        if event.get("type") == "done":
            yield {"type": "done", "prep": prep_result(event["prep"]).model_dump(mode="json")}
        else:
            yield event


def topics_response(vacancy_id: str, stage: str, rows) -> PrepTopicsResponse:
    """Слабые сверху, уверенные снизу — так владелец сразу видит пробелы."""
    rank = {"weak": 0, "medium": 1, "confident": 2}
    items = sorted(
        [PrepTopicOut(topic=r.topic, level=r.level, packs_reviewed=r.packs_reviewed) for r in rows],
        key=lambda t: (rank.get(t.level, 1), t.topic.lower()),
    )
    return PrepTopicsResponse(vacancy_id=vacancy_id, stage=stage, items=items)


def sobes_context_response(overlay: SobesOverlay) -> PrepSobesContextResponse:
    return PrepSobesContextResponse(
        available=overlay.available,
        markdown=overlay.markdown,
        stage=cast(PrepStage, overlay.stage),
        stage_label=STAGE_LABELS.get(overlay.stage, overlay.stage),
        char_count=overlay.char_count,
        char_limit=overlay.char_limit,
    )


def prep_chat_response(reply: PrepChatReply) -> PrepChatResponse:
    from api.routers.assistant.mappers import prep_chat_message

    return PrepChatResponse(
        message=prep_chat_message(reply.message),
        questions=[prep_question_out(q) for q in reply.questions],
        topic=reply.topic,
    )


# --------------------------------------------------------------------------- разборы


def debrief_out(
    vacancy_id: str,
    stage: str,
    analysis: DebriefAnalysis,
    *,
    transcript: str = "",
    record_id: int | None = None,
    interview_stage_id: int | None = None,
    resolution: str = "pending",
    resolved_at=None,
    resolved_note: str = "",
    created_at=None,
    attachments: Sequence[AttachmentMeta] = (),
) -> DebriefResult:
    return DebriefResult(
        vacancy_id=vacancy_id,
        stage=stage,  # type: ignore[arg-type]
        stage_label=STAGE_LABELS.get(stage, stage),
        signal_label=SIGNAL_LABELS_WEB.get(analysis.next_steps_signal, analysis.next_steps_signal),
        format_label=INTERVIEW_FORMAT_LABELS.get(
            analysis.interview_format, analysis.interview_format
        ),
        analysis=analysis,
        transcript=transcript,
        id=record_id,
        interview_stage_id=interview_stage_id,
        resolution=resolution,  # type: ignore[arg-type]
        resolved_at=resolved_at,
        resolved_note=resolved_note,
        created_at=created_at,
        attachments=[attachment_meta_out(a) for a in attachments],
    )


def debrief_result(result: DebriefScenarioResult) -> DebriefResult:
    return debrief_out(
        result.vacancy_id,
        result.stage,
        result.analysis,
        transcript=result.transcript,
        record_id=result.id,
        interview_stage_id=result.interview_stage_id,
        created_at=result.created_at,
        attachments=result.attachments,
    )


def debrief_record_out(
    rec, analysis: DebriefAnalysis, attachments: Sequence[AttachmentMeta] = ()
) -> DebriefResult:
    return debrief_out(
        rec.vacancy_id,
        rec.stage,
        analysis,
        transcript=rec.transcript,
        record_id=rec.id,
        interview_stage_id=rec.interview_stage_id,
        resolution=rec.resolution,
        resolved_at=rec.resolved_at,
        resolved_note=rec.resolved_note,
        created_at=rec.created_at,
        attachments=attachments,
    )


def debrief_history(
    vacancy_id: str, records, attachments_map: dict[int, list[AttachmentMeta]] | None = None
) -> DebriefHistory:
    from core.domains.preparation.scenarios import parse_analysis

    attachments_map = attachments_map or {}
    items: list[DebriefResult] = []
    for rec in records:
        analysis = parse_analysis(rec.analysis)
        if analysis is None:  # битый jsonb не должен ронять всю историю
            continue
        items.append(debrief_record_out(rec, analysis, attachments_map.get(rec.id or 0, [])))
    return DebriefHistory(vacancy_id=vacancy_id, items=items)


# --------------------------------------------------------------------------- цепочка этапов


def stage_out(stage: InterviewStage) -> InterviewStageOut:
    return InterviewStageOut(
        id=stage.id or 0,
        vacancy_id=stage.vacancy_id,
        stage_type=stage.stage_type,  # type: ignore[arg-type]
        stage_label=STAGE_TYPE_LABELS.get(stage.stage_type, stage.stage_type),
        scheduled_at=stage.scheduled_at,
        format=stage.format,  # type: ignore[arg-type]
        status=stage.status,  # type: ignore[arg-type]
        position=stage.position,
        notes=stage.notes,
        source_message_id=stage.source_message_id,
        created_at=stage.created_at,
    )


def stages_list(vacancy_id: str, stages) -> InterviewStageListResponse:
    return InterviewStageListResponse(vacancy_id=vacancy_id, items=[stage_out(s) for s in stages])


# --------------------------------------------------------------------------- скрининг


def _question_group(g: dict) -> QuestionGroup | None:
    """jsonb-словарь → типизированная QuestionGroup. Битую группу пропускаем."""
    if not isinstance(g, dict) or not g.get("title"):
        return None
    questions = [
        ScreeningQuestion(
            question=str(q["question"]),
            probe=str(q.get("probe", "")),
            expect=str(q.get("expect", "")),
        )
        for q in (g.get("questions") or [])
        if isinstance(q, dict) and q.get("question")
    ]
    if not questions:
        return None
    return QuestionGroup(title=str(g["title"]), hook=str(g.get("hook", "")), questions=questions)


def _hr_question(q: dict) -> HrQuestion | None:
    if not isinstance(q, dict) or not q.get("question"):
        return None
    draft = str(q.get("draft_answer") or "").strip()
    if not draft:
        return None
    return HrQuestion(
        question=str(q["question"]),
        requirement=str(q.get("requirement", "")),
        intent=str(q.get("intent", "")),
        draft_answer=draft,
    )


def _pitch_block(b: dict) -> PitchBlock | None:
    if not isinstance(b, dict) or not b.get("label"):
        return None
    lines = [str(line) for line in (b.get("lines") or []) if str(line).strip()]
    if not lines:
        return None
    return PitchBlock(label=str(b["label"]), lines=lines)


def _typed(rows, factory) -> list:
    out = []
    for raw in rows or []:
        typed = factory(raw) if isinstance(raw, dict) else None
        if typed is not None:
            out.append(typed)
    return out


def screening_pack(saved) -> SavedScreeningQuestions:
    """Строка `screening_questions` → типизированный пакет (битые куски пропускаем)."""
    return SavedScreeningQuestions(
        vacancy_id=saved.vacancy_id,
        groups=_typed(saved.groups, _question_group),
        hr_questions=_typed(saved.hr_questions, _hr_question),
        why_company=saved.why_company or "",
        oral_pitch=saved.oral_pitch or "",
        pitch_blocks=_typed(saved.pitch_blocks, _pitch_block),
        jd_brief=saved.jd_brief or {},
        generated_at=saved.generated_at,
    )


async def screening_sse_payloads(
    events: AsyncIterator[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Доменные события сборки пакета → payload'ы единого SSE.

    `partial` может нести уже сохранённые в БД `hr_questions`/`groups` (`_partial_from`
    подмешивает их as-is при "brief", ещё до своего "questions"-события) — старые записи,
    сохранённые до появления поля `requirement` у `HrQuestion`, тогда идут без него, и
    фронтенд падает на `q.requirement.trim()`. Прогоняем через те же мапперы, что и `done`.
    """
    async for event in events:
        if event.get("type") == "done":
            pack = screening_pack(event["saved"]).model_dump(mode="json")
            yield {"type": "done", "pack": pack}
        elif "partial" in event:
            partial = dict(event["partial"])
            partial["hr_questions"] = [
                q.model_dump(mode="json") for q in _typed(partial.get("hr_questions"), _hr_question)
            ]
            partial["groups"] = [
                g.model_dump(mode="json") for g in _typed(partial.get("groups"), _question_group)
            ]
            yield {**event, "partial": partial}
        else:
            yield event


__all__ = [
    "company_profile_out",
    "debrief_history",
    "debrief_out",
    "debrief_record_out",
    "debrief_result",
    "prep_chat_response",
    "prep_question_out",
    "prep_result",
    "prep_sse_payloads",
    "screening_pack",
    "screening_sse_payloads",
    "sobes_context_response",
    "stage_out",
    "stages_list",
    "topics_response",
    "vacancy_ref",
]
