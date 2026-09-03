"""Разбор прошедшего собеса.

Кросс-доменный сценарий: LLM-разбор и его хвосты (прогресс цепочки этапов, матчинг вопросов,
леджер компетенций) — `preparation`, краткая сводка для дайджеста «молчащий HR» —
`opportunities.enrichment`. Раньше вся эта последовательность жила в
`api/routers/preparation/debrief.py`.

Правило хвостов: ни один из них не имеет права уронить уже полученный разбор — каждый идёт
под своим таймаутом и глотает ошибку. Сам разбор без Postgres тоже отдаётся, просто без записи.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field

from core.domains.assistant.attachments.models import AttachmentMeta
from core.domains.preparation.interview.debrief import analyze_debrief, extract_sobes_transcript
from core.domains.preparation.models import (
    SIGNAL_LABELS_WEB,
    STAGE_LABELS,
    DebriefAnalysis,
)
from core.domains.preparation.scenarios import VacancyRef, build_record
from core.kernel.errors import InvalidInput, LlmError

logger = logging.getLogger(__name__)

#: Минимальная длина транскрипта, из которой ещё можно что-то вытащить.
MIN_TRANSCRIPT = 20

#: Потолок на каждый побочный эффект разбора — хвост не должен держать ответ.
_TAIL_TIMEOUT = 8
# Хвосты с собственным LLM-вызовом (пересчёт скора / этапы из расшифровки) не укладываются в
# 8с — под капотом hr_facts (budget_ms 30с) и/или job_search-скоринг (budget_ms 60с) /
# next_stage_hint (budget_ms 20с). Разбор и так уже фоновая задача (job_id + поллинг, см.
# api/routers/preparation/debrief.py) — эти хвосты просто добавляют время до "готово", а не
# держат HTTP-поток.
_LLM_TAIL_TIMEOUT = 95


class DebriefResult(BaseModel):
    """Разбор + его место в истории (id/created_at пустые, если Postgres не отвечал).

    `attachments` (Э4-4, план chat_image_attachments) — скрины собеса/транскрипции: распознанный
    текст владелец уже видел и правил в поле расшифровки ДО анализа (плана «носитель текста»),
    сюда они попадают только для показа в карточке разбора — привязываются к `id` уже после
    сохранения (см. `_store`).
    """

    vacancy_id: str
    stage: str
    analysis: DebriefAnalysis
    transcript: str = ""
    id: int | None = None
    interview_stage_id: int | None = None
    created_at: datetime | None = None
    attachments: list[AttachmentMeta] = Field(default_factory=list)


def clean_transcript(raw: str) -> str:
    """Транскрипт из вставки sobes.tech; слишком короткий — 400 (валидируется до фоновой задачи)."""
    transcript = extract_sobes_transcript(raw or "")
    if len(transcript) < MIN_TRANSCRIPT:
        raise InvalidInput("Транскрипт слишком короткий для разбора")
    return transcript


async def analyze(
    ref: VacancyRef,
    *,
    stage: str,
    transcript: str,
    account_id: int,
    interview_stage_id: int | None = None,
    attachment_ids: Sequence[int] = (),
) -> DebriefResult:
    """Разобрать транскрипт (LLM), записать в историю и разослать побочные эффекты.

    `attachment_ids` (Э4-4) — скрины собеса/транскрипции, уже загруженные до отправки: их текст
    владелец сам вмешал в `transcript` через композер (плана), здесь они только привязываются
    к сохранённому разбору для показа в карточке — на сам LLM-анализ не влияют.
    """
    clean = clean_transcript(transcript)
    logger.info("debrief: vacancy_id=%s stage=%s", ref.vacancy_id, stage)

    try:
        analysis = await analyze_debrief(
            build_record(ref, fallback_text=""),
            clean,
            account_id=account_id,
            stage_label=STAGE_LABELS.get(stage, stage),
            prior_context=await _prior_context(ref.vacancy_id, account_id=account_id),
        )
    except ValueError as exc:
        raise InvalidInput(str(exc)) from exc
    except TimeoutError as exc:
        logger.error("debrief LLM timeout: %s", exc)
        raise LlmError(str(exc)) from exc

    result = DebriefResult(
        vacancy_id=ref.vacancy_id,
        stage=stage,
        analysis=analysis,
        transcript=clean,
        interview_stage_id=interview_stage_id,
    )
    saved = await _store(result, account_id=account_id, attachment_ids=attachment_ids)
    await _tails(result, account_id=account_id)
    return saved


# --------------------------------------------------------------------------- внутреннее


async def _prior_context(vacancy_id: str, *, account_id: int) -> str:
    """Сжатые разборы предыдущих этапов — следующий разбор учитывает, что уже было.

    Хронологический порядок (старые → новые), по каждому этапу: сигнал, о чём спрашивали,
    какие темы были слабыми. Нет PG → пустая строка, разбор всё равно идёт.
    """
    from core.domains.preparation.scenarios import debrief_history, parse_analysis

    blocks: list[str] = []
    for rec in reversed(await debrief_history(vacancy_id, limit=10, account_id=account_id)):
        analysis = parse_analysis(rec.analysis)
        if analysis is None:
            continue
        label = STAGE_LABELS.get(rec.stage, rec.stage)
        signal = SIGNAL_LABELS_WEB.get(analysis.next_steps_signal, analysis.next_steps_signal)
        lines = [f"### {label} (сигнал: {signal}, впечатление {analysis.overall_impression}/10)"]
        if analysis.summary.strip():
            lines.append(analysis.summary.strip())
        if analysis.questions_asked:
            lines.append("Спрашивали: " + "; ".join(analysis.questions_asked[:8]))
        if analysis.topics_to_study:
            lines.append("Слабые темы: " + "; ".join(analysis.topics_to_study[:8]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def _store(
    result: DebriefResult, *, account_id: int, attachment_ids: Sequence[int] = ()
) -> DebriefResult:
    """Накопление истории: разбор отдельной строкой. Нет PG → no-op, разбор уже готов."""
    try:
        from core.domains.preparation.debrief import DebriefRecord, save_debrief

        saved = await asyncio.wait_for(
            save_debrief(
                DebriefRecord(
                    vacancy_id=result.vacancy_id,
                    stage=result.stage,
                    transcript=result.transcript,
                    signal=result.analysis.next_steps_signal,
                    impression=result.analysis.overall_impression,
                    summary=result.analysis.summary,
                    analysis=result.analysis.model_dump(mode="json"),
                    interview_stage_id=result.interview_stage_id,
                ),
                account_id=account_id,
            ),
            timeout=_TAIL_TIMEOUT,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → разбор отдаётся без персиста
        logger.debug("debrief: разбор не сохранён (Postgres недоступен): %s", exc)
        return result

    attachments: list[AttachmentMeta] = []
    if attachment_ids and saved.id is not None:
        try:
            from core.domains.assistant.attachments import service as attachments_service

            await attachments_service.link_to_debrief(
                saved.id, list(attachment_ids), account_id=account_id
            )
            loaded = await attachments_service.load_for_debriefs([saved.id], account_id=account_id)
            attachments = loaded.get(saved.id, [])
        except Exception as exc:  # noqa: BLE001 — вложения не должны ронять уже готовый разбор
            logger.debug("debrief: вложения не привязаны (debrief_id=%s): %s", saved.id, exc)

    return result.model_copy(
        update={"id": saved.id, "created_at": saved.created_at, "attachments": attachments}
    )


async def _tails(result: DebriefResult, *, account_id: int) -> None:
    """Побочные эффекты разбора. Каждый best-effort и под таймаутом — ответ уже сформирован."""
    # Авто-прогресс цепочки этапов: завершаем именно ту строку, к которой владелец явно привязал
    # транскрипт. Без `interview_stage_id` угадывание по этапу подготовки не работало (разные
    # таксономии PrepStage / InterviewStageType) и всегда тихо no-op'ило — убрано.
    if result.interview_stage_id is not None:
        from core.domains.preparation.interview_stages import complete_stage_by_id

        await _safe(
            "авто-прогресс цепочки",
            complete_stage_by_id(result.interview_stage_id, account_id=account_id),
        )

    from core.domains.preparation.interview.question_match import (
        match_session_questions_safe,
        record_competency_ledger_safe,
    )

    # Жизненный цикл вопросов подготовки: реально заданные вопросы сматчить с заготовленными.
    await _safe(
        "матчинг вопросов подготовки",
        match_session_questions_safe(
            result.vacancy_id,
            result.stage,
            result.analysis.questions_asked,
            account_id=account_id,
            question_mastery=result.analysis.question_mastery,
        ),
    )
    # Карта компетенций: темы разбора канонизируются в леджер — траектория weak → confident.
    await _safe(
        "леджер компетенций",
        record_competency_ledger_safe(
            result.vacancy_id,
            result.stage,
            result.id,
            result.analysis.competency_map,
            account_id=account_id,
        ),
    )

    from core.domains.opportunities.enrichment import merge_enrichment

    # Краткая сводка в enrichment — её читает дайджест «молчащий HR».
    await _safe(
        "enrichment",
        merge_enrichment(
            result.vacancy_id,
            interview_debrief=result.analysis.summary,
            account_id=account_id,
        ),
    )

    # Расшифровка HR-скрининга — то же слово рекрутера, что и переписка: пусть перекрывает скор
    # (только screening — техничка/финал про код, не про условия вакансии).
    if result.stage == "screening":
        from core.domains.opportunities.recalibrate import rescore_from_hr_facts_safe

        await _safe(
            "пересчёт по расшифровке скрининга",
            rescore_from_hr_facts_safe(
                result.vacancy_id, trigger="screening_debrief", account_id=account_id
            ),
            timeout=_LLM_TAIL_TIMEOUT,
        )

        if result.transcript.strip():
            from core.domains.preparation.interview.next_stage import apply_next_stage_safe

            await _safe(
                "этапы из расшифровки скрининга",
                apply_next_stage_safe(result.vacancy_id, result.transcript, account_id=account_id),
                timeout=_LLM_TAIL_TIMEOUT,
            )


async def _safe(what: str, coro, *, timeout: float = _TAIL_TIMEOUT) -> None:
    try:
        await asyncio.wait_for(coro, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — хвост не должен ронять разбор
        logger.debug("debrief: %s не выполнен: %s", what, exc)


async def load_attachments(
    debrief_ids: Sequence[int], *, account_id: int
) -> dict[int, list[AttachmentMeta]]:
    """Вложения уже сохранённых разборов (Э4-4) — история и точечная правка транскрипта
    (`api/routers/preparation/debrief.py`), сам `analyze()` заполняет их сам через `_store`."""
    ids = [i for i in debrief_ids if i is not None]
    if not ids:
        return {}
    from core.domains.assistant.attachments import service as attachments_service

    return await attachments_service.load_for_debriefs(ids, account_id=account_id)


__all__ = [
    "MIN_TRANSCRIPT",
    "DebriefResult",
    "analyze",
    "clean_transcript",
    "load_attachments",
]
