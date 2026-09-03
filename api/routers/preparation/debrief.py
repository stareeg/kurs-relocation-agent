"""Вкладка «Разбор»: структурный разбор транскрипта прошедшего собеса.

Кросс-доменный сценарий (preparation + opportunities.enrichment) —
`core.app.scenarios.debrief`. Job-паттерн опроса остаётся в транспорте:
in-process состояние не переживает рестарт и к домену не относится.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException

from api.errors import to_http
from api.routers.preparation.mappers import (
    debrief_history,
    debrief_record_out,
    debrief_result,
    vacancy_ref,
)
from api.schemas import (
    DebriefAnalyzeRequest,
    DebriefHistory,
    DebriefJobStarted,
    DebriefJobStatus,
    DebriefResult,
    DebriefStageIndex,
    DebriefStageMark,
    DebriefTranscriptPatch,
)
from api.security import AccountContext, require_account_context
from core.app.scenarios.debrief import analyze, clean_transcript, load_attachments
from core.domains.preparation import scenarios as prep
from core.kernel.errors import DomainError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/debrief", tags=["debrief"])

_MAX_JOBS = 50


@dataclass
class _DebriefJob:
    status: str = "running"  # running|done|error
    result: DebriefResult | None = None
    error: str | None = None
    started: float = field(default_factory=time.monotonic)


_JOBS: dict[str, _DebriefJob] = {}


def _prune_jobs() -> None:
    if len(_JOBS) <= _MAX_JOBS:
        return
    terminal = [jid for jid, j in _JOBS.items() if j.status != "running"]
    for jid in terminal[: len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(jid, None)


async def _run_job(
    job_id: str, vacancy_id: str, body: DebriefAnalyzeRequest, *, account_id: int
) -> None:
    job = _JOBS[job_id]
    try:
        result = await analyze(
            vacancy_ref(vacancy_id, body),
            stage=body.stage,
            transcript=body.transcript,
            account_id=account_id,
            interview_stage_id=body.interview_stage_id,
            attachment_ids=body.attachment_ids,
        )
        job.result = debrief_result(result)
        job.status = "done"
    except DomainError as exc:
        job.error = exc.message
        job.status = "error"
    except Exception as exc:  # noqa: BLE001 — фон не должен ронять процесс
        logger.exception("debrief: job %s (vacancy_id=%s) упал: %s", job_id, vacancy_id, exc)
        job.error = str(exc)
        job.status = "error"


@router.post("/{vacancy_id}/analyze", response_model=DebriefJobStarted, status_code=202)
async def start_analyze(
    vacancy_id: str,
    body: DebriefAnalyzeRequest,
    account: AccountContext = Depends(require_account_context),
) -> DebriefJobStarted:
    """Завести фоновую задачу разбора и сразу отдать job_id — без ожидания LLM на HTTP."""
    try:
        clean_transcript(body.transcript or "")
    except DomainError as exc:
        raise to_http(exc) from exc
    job_id = uuid.uuid4().hex
    _JOBS[job_id] = _DebriefJob()
    _prune_jobs()
    asyncio.create_task(_run_job(job_id, vacancy_id, body, account_id=account.account_id))
    return DebriefJobStarted(job_id=job_id, status="running")


@router.get("/{vacancy_id}/analyze/{job_id}", response_model=DebriefJobStatus)
async def analyze_status(vacancy_id: str, job_id: str) -> DebriefJobStatus:
    """Опрос статуса фоновой задачи разбора."""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404, detail="Задача разбора не найдена (истекла или сервер перезапущен)"
        )
    return DebriefJobStatus(status=job.status, result=job.result, error=job.error)


# Объявлен ДО "/{vacancy_id}" — иначе FastAPI матчит "stage-index" как vacancy_id.
@router.get("/stage-index", response_model=DebriefStageIndex)
async def stage_index(
    account: AccountContext = Depends(require_account_context),
) -> DebriefStageIndex:
    """Где у аккаунта уже есть разобранная расшифровка — vacancy_id → этапы.

    Рельс Скринингов/Техничек рисует по этому индексу отметку на карточке вакансии: иначе
    пришлось бы тянуть историю разборов на каждую карточку списка.
    """
    pairs = await prep.debrief_stage_index(account_id=account.account_id)
    by_vacancy: dict[str, list[str]] = {}
    for vacancy_id, stage in pairs:
        by_vacancy.setdefault(vacancy_id, []).append(stage)
    return DebriefStageIndex(
        items=[
            DebriefStageMark(vacancy_id=vid, stages=sorted(stages))
            for vid, stages in sorted(by_vacancy.items())
        ]
    )


@router.get("/{vacancy_id}", response_model=DebriefHistory)
async def history(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> DebriefHistory:
    """История разборов по вакансии (свежие первыми). Нет PG → пустой список."""
    records = await prep.debrief_history(vacancy_id, account_id=account.account_id)
    attachments_map = await load_attachments(
        [r.id for r in records if r.id is not None], account_id=account.account_id
    )
    return debrief_history(vacancy_id, records, attachments_map)


@router.patch("/{vacancy_id}/{debrief_id}", response_model=DebriefResult)
async def patch_transcript(
    vacancy_id: str,
    debrief_id: int,
    body: DebriefTranscriptPatch,
    account: AccountContext = Depends(require_account_context),
) -> DebriefResult:
    """Поправить текст транскрипта в ленте — без повторного LLM-разбора."""
    try:
        rec = await prep.patch_debrief_transcript(
            vacancy_id, debrief_id, body.transcript, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    attachments_map = await load_attachments([debrief_id], account_id=account.account_id)
    return debrief_record_out(rec, prep.analysis_of(rec), attachments_map.get(debrief_id, []))
