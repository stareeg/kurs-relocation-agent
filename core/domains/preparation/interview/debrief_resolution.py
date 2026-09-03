"""Жизненный цикл сигнала разбора: жёлтый → зелёный/красный (авто-отказ).

Каждый свежий разбор транскрипта стартует `resolution='pending'` (жёлтый) — собственная оценка
кандидата не финальна, ровно как решил владелец. Подтверждение или опровержение прилетает только
из ПОСЛЕДУЮЩЕЙ переписки с HR («Диалог» вакансии): назначили следующий этап / заговорили про оффер
→ `advanced` (зелёный); явный отказ именно по этому этапу → `rejected` (красный) + вакансия
автоматически уезжает в «Отказ» — это «дорогой» отказ (после реального собеса, не на этапе отклика).

Триггер — каждое новое входящее HR-сообщение (`api/routers/conversations.py`), по образцу
`rescore_from_hr_facts_safe`/`extract_event_safe`: best-effort, не должен ронять ввод сообщения.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.preparation.debrief import (
    DebriefRecord,
    load_latest_pending_debrief,
    mark_debrief_resolution,
)
from core.domains.preparation.models import STAGE_LABELS
from core.kernel import ports
from core.kernel.errors import LlmError
from core.kernel.schemas.funnel import FunnelStatus
from core.platform.db.pool import Executor

logger = logging.getLogger(__name__)

# Канон причины отказа (frontend/src/features/jobs/reject-reasons.ts: HR_REJECT_REASONS) — тот же
# ярлык, что владелец выбирает руками при отказе после техничками.
_AUTO_REJECT_REASON = "Не прошёл техничку"


class _ResolutionVerdict(BaseModel):
    """Ответ дешёвого LLM-классификатора (тир extract) по новым репликам «Диалога»."""

    resolution: Literal["advanced", "rejected", "pending"] = "pending"
    note: str = Field(default="", max_length=500)


_SYSTEM = """Ты помогаешь понять, как переписка с HR/рекрутером ПОСЛЕ конкретного этапа
собеседования повлияла на исход именно этого этапа.

Верни ТОЛЬКО JSON: {"resolution": "<advanced|rejected|pending>", "note": "<кратко на русском, до 200 символов>"}

Правила:
- "advanced" — HR явно назначил следующий этап, подтвердил переход дальше, заговорил про оффер.
- "rejected" — явный отказ именно по этому этапу («к сожалению», «выбрали другого кандидата»,
  «не продолжаем», «не подходите нам сейчас»).
- "pending" — переписка есть, но однозначного сигнала пока нет — не гадай, оставляй pending.
- Решение только по словам HR/рекрутера в переписке, НЕ по тому, как кандидат сам оценил своё
  выступление в разборе (собственная оценка не финальна, это лишь контекст, что обсуждалось).
"""


def _debrief_context(record: DebriefRecord) -> str:
    label = STAGE_LABELS.get(record.stage, record.stage)
    lines = [f"Этап: {label}"]
    analysis = record.analysis or {}
    summary = str(analysis.get("summary") or "").strip()
    if summary:
        lines.append(f"Итог разбора кандидатом: {summary}")
    topics = analysis.get("topics_to_study") or []
    if topics:
        lines.append("Слабые темы (со слов кандидата): " + "; ".join(str(t) for t in topics[:8]))
    return "\n".join(lines)


def _correspondence_context(new_messages: list) -> str:
    lines = []
    for m in new_messages:
        who = "HR" if m.kind == "hr_in" else "Кандидат"
        body = (m.body or "").strip()
        if body:
            lines.append(f"[{who}] {body}")
    return "\n".join(lines)


async def resolve_pending_debrief_signal(
    vacancy_id: str, *, trigger: str = "hr_message", account_id: int, db: Executor | None = None
) -> DebriefRecord | None:
    """Резолвнуть самый свежий pending-разбор вакансии по новым репликам «Диалога».

    None — нечего резолвить (нет pending-разборов, нет треда, нет новых hr_in реплик после разбора,
    или LLM вернула "pending" — сигнал пока неоднозначный, остаёмся жёлтыми).
    """
    if not vacancy_id:
        return None

    debrief = await load_latest_pending_debrief(vacancy_id, account_id=account_id, db=db)
    if debrief is None or debrief.id is None:
        return None

    from core.domains.pipeline.hr_threads import get_primary_thread, list_messages

    thread = await get_primary_thread(vacancy_id, account_id=account_id, db=db)
    if thread is None or thread.id is None:
        return None

    messages = await list_messages(thread.id, account_id=account_id, db=db)
    created_at = debrief.created_at
    new_hr_in = [
        m
        for m in messages
        if m.kind == "hr_in" and created_at is not None and (m.sent_at or created_at) > created_at
    ]
    if not new_hr_in:
        return None

    user = "\n\n".join(
        part
        for part in (
            _debrief_context(debrief),
            "Новые реплики переписки после разбора:\n" + _correspondence_context(messages),
        )
        if part.strip()
    )

    try:
        # Раньше вызов шёл мимо реестра (agent="system" + tier="extract") — теперь у него
        # своя декларация `debrief_resolution`, тир и лимиты живут там.
        verdict = await ports.llm().structured(
            "debrief_resolution",
            schema=_ResolutionVerdict,
            system=_SYSTEM,
            user=user,
        )
    except LlmError as exc:
        logger.warning("debrief_resolution: LLM недоступен (vacancy_id=%s): %s", vacancy_id, exc)
        return None

    if verdict.resolution == "pending":
        logger.info(
            "debrief_resolution: vacancy_id=%s разбор #%s остаётся pending (%s)",
            vacancy_id,
            debrief.id,
            verdict.note,
        )
        return None

    updated = await mark_debrief_resolution(
        debrief.id, verdict.resolution, verdict.note, account_id=account_id, db=db
    )

    if verdict.resolution == "rejected":
        await _apply_auto_reject(vacancy_id, debrief, verdict.note, account_id=account_id, db=db)

    logger.info(
        "debrief_resolution: vacancy_id=%s разбор #%s → %s (триггер=%s)",
        vacancy_id,
        debrief.id,
        verdict.resolution,
        trigger,
    )
    return updated


async def _apply_auto_reject(
    vacancy_id: str,
    debrief: DebriefRecord,
    note: str,
    *,
    account_id: int,
    db: Executor | None = None,
) -> None:
    """Красный: этап помечается failed, вакансия уезжает в «Отказ» (идемпотентно), фиксируется причина."""
    from core.domains.preparation.interview_stages import fail_stage

    if debrief.interview_stage_id is not None:
        await fail_stage(debrief.interview_stage_id, account_id=account_id, db=db)

    from core.domains.opportunities.jobs import add_stage, get_job_by_vacancy_id

    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id, db=db)
    terminal = {FunnelStatus.REJECTED.value, FunnelStatus.ARCHIVE.value}
    if job is not None and job.id is not None and job.status not in terminal:
        await add_stage(
            job.id,
            FunnelStatus.REJECTED.value,
            source="debrief_auto_reject",
            account_id=account_id,
            db=db,
        )

    from core.domains.pipeline.stage_outcome import StageOutcomeRecord, save_stage_outcome

    feedback = _AUTO_REJECT_REASON + (f". {note.strip()}" if note.strip() else "")
    await save_stage_outcome(
        StageOutcomeRecord(
            vacancy_id=vacancy_id,
            stage=debrief.stage,
            outcome="rejected",
            recruiter_feedback=feedback,
        ),
        account_id=account_id,
        db=db,
    )


async def resolve_pending_debrief_signal_safe(
    vacancy_id: str, *, trigger: str = "hr_message", account_id: int, db: Executor | None = None
) -> None:
    """Best-effort обёртка для фоновых триггеров: глушит исключения (не должна ронять ввод сообщения)."""
    try:
        await resolve_pending_debrief_signal(
            vacancy_id, trigger=trigger, account_id=account_id, db=db
        )
    except Exception as exc:  # noqa: BLE001 — фоновый best-effort
        logger.warning("debrief_resolution: vacancy_id=%s упал (best-effort): %s", vacancy_id, exc)


__all__ = ["resolve_pending_debrief_signal", "resolve_pending_debrief_signal_safe"]
