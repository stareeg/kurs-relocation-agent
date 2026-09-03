"""Превью очереди автооткликов: что система взяла бы сама, что оставила на ручной разбор.

Живой пересчёт (`core.domains.pipeline.auto_apply.preview_queue`) — см.
`core/domains/pipeline/auto_apply/README.md` (Фаза 1: только решение, без реальной отправки).
Настройки — через `GET/PATCH /api/settings` (`auto_apply_config`), не здесь.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.errors import to_http
from api.schemas import (
    AnketaConfirmRequest,
    AnketaPendingItem,
    AnketaPendingResponse,
    AutoApplyClearResponse,
    AutoApplyDailyCountResponse,
    AutoApplyDecision,
    AutoApplyManualSendResponse,
    AutoApplyMoveRequest,
    AutoApplyPauseResponse,
    AutoApplyPlatform,
    AutoApplyPreviewItem,
    AutoApplyPreviewResponse,
    AutoApplyReportRequest,
    AutoApplyReportResponse,
    AutoApplySchedule,
    AutoApplyTickReport,
)
from api.security import AccountContext, require_account_context
from core.app.scenarios.auto_apply import (
    auto_apply_schedule,
    clear_queue,
    confirm_anketa,
    list_pending_anketas,
    pause_all,
    preview_with_pregen,
    reject_anketa,
    report_attempt,
    report_tick_summary,
)
from core.domains.opportunities.jobs import Job, get_job
from core.domains.opportunities.models import AnketaState
from core.domains.pipeline.auto_apply import (
    auto_apply_daily_hard_cap,
    count_today,
    get_auto_apply_config,
    is_platform_limited_today,
    last_real_apply_at,
    set_override,
)
from core.domains.pipeline.auto_apply.runtime_state import (
    is_manual_send_pending,
    set_manual_send_pending,
)
from core.kernel.errors import DomainError, InvalidInput, NotFound
from core.platform.observability import event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline/auto-apply", tags=["auto-apply"])


def _item(
    job: Job,
    decision: AutoApplyDecision,
    *,
    failure_reason: str | None = None,
) -> AutoApplyPreviewItem:
    return AutoApplyPreviewItem(
        job_id=job.id or 0,
        vacancy_id=job.vacancy_id or "",
        url=job.url,
        title=job.title,
        company=job.company,
        overall_score=job.overall_score,
        decision=decision,
        letter_required=job.letter_required,
        cover_letter_text=job.cover_letter_text,
        anketa=AnketaState.model_validate(job.anketa) if job.anketa else None,
        failure_reason=failure_reason,
    )


@router.get("/preview", response_model=AutoApplyPreviewResponse)
async def preview_auto_apply(
    platform: AutoApplyPlatform,
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyPreviewResponse:
    """Разбить непросмотренные-до-отклика вакансии площадки на auto / manual_review."""
    result = await preview_with_pregen(platform, account_id=account.account_id)
    sched = await auto_apply_schedule(account_id=account.account_id)
    # Флаг ручной отправки здесь только отдаётся наружу, без записи в журнал: «Расширение»
    # опрашивает превью раз в 5 секунд, и строка на каждый опрос давала бы сотни одинаковых
    # записей за один клик. Жизненный цикл флага виден по `/manual-send` и `/clear-manual-send`.
    pending = await is_manual_send_pending(account_id=account.account_id)
    return AutoApplyPreviewResponse(
        platform=result.platform,
        enabled=result.enabled,
        auto=[_item(j, "auto") for j in result.auto],
        manual_review=[
            _item(
                j,
                "manual_review",
                failure_reason=result.failure_reasons.get(j.id) if j.id is not None else None,
            )
            for j in result.manual_review
        ],
        applied=[_item(j, "applied") for j in result.applied],
        schedule=AutoApplySchedule(
            runner_last_tick_at=sched.runner_last_tick_at,
            tick_seconds=sched.tick_seconds,
            real_per_tick=sched.real_per_tick,
            gap_seconds=sched.gap_seconds,
            min_gap_seconds=sched.min_gap_seconds,
        ),
        manual_send_pending=pending,
    )


@router.post("/{job_id}/move", response_model=AutoApplyPreviewItem)
async def move_queue_item(
    job_id: int,
    body: AutoApplyMoveRequest,
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyPreviewItem:
    """Квик-экшен «переместить» (Фаза E редизайна «Расширения», пункт 4) — ручной оверрайд
    бакета auto/manual_review; переживает следующий пересчёт превью (см. overrides.py)."""
    job = await get_job(job_id, account_id=account.account_id)
    if job is None:
        raise to_http(NotFound(f"вакансия не найдена: job_id={job_id}"))
    await set_override(job_id, body.target, account_id=account.account_id)
    return _item(job, body.target)


@router.get("/daily-count", response_model=AutoApplyDailyCountResponse)
async def daily_count(
    platform: AutoApplyPlatform,
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyDailyCountResponse:
    """Сколько автооткликов площадки уже ушло сегодня (2.7) — раннер спрашивает перед каждым
    следующим кандидатом и останавливается на cap.

    Фаза 8.2: если площадка сегодня уже сигналила о СВОЁМ дневном лимите (`platform_limit`,
    не наш `cap`) — считаем бюджет исчерпанным здесь же, без отдельной ручки у раннера
    (`count` подтягивается до `cap`, `remaining` = 0 тем же путём, что и обычный cap).

    `cap` (2026-08-28) — жёсткий потолок площадки (`auto_apply_daily_hard_cap`), а не ручка
    пользователя: слайдер «Лимит за очередь» убран, `daily_cap` в конфиге больше не читается."""
    cap = auto_apply_daily_hard_cap(platform)
    count = await count_today(platform, account_id=account.account_id)
    if count < cap and await is_platform_limited_today(platform, account_id=account.account_id):
        count = cap
    remaining = max(cap - count, 0)
    last_real = await last_real_apply_at(platform, account_id=account.account_id)
    return AutoApplyDailyCountResponse(
        platform=platform,
        count=count,
        cap=cap,
        remaining=remaining,
        last_real_apply_at=last_real,
    )


@router.post("/report", response_model=AutoApplyReportResponse)
async def report(
    body: AutoApplyReportRequest,
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyReportResponse:
    """Раннер сообщает об одной попытке (2.1/2.2) — всегда лог, стадия воронки только не
    dry-run. `dry_run` по умолчанию True в схеме — забытый флаг никогда не двигает воронку."""
    try:
        job = await report_attempt(
            body.platform,
            job_id=body.job_id,
            vacancy_id=body.vacancy_id,
            dry_run=body.dry_run,
            account_id=account.account_id,
            outcome=body.outcome,
            anketa_questions=body.anketa_questions,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return AutoApplyReportResponse(
        platform=body.platform, dry_run=body.dry_run, status=job.status if job else None
    )


@router.post("/tick-report", status_code=204)
async def tick_report(
    body: AutoApplyTickReport,
    account: AccountContext = Depends(require_account_context),
) -> None:
    """Раннер расширения шлёт итог тика (heartbeat) — одна строка в журнал + `last_tick` в
    рантайм-стейт. INFO если всё ок, WARNING если раннер хотел работать, но не смог."""
    await report_tick_summary(
        account_id=account.account_id,
        platforms_enabled=body.platforms_enabled,
        platforms_ready=body.platforms_ready,
        candidates=body.candidates,
        applied=body.applied,
        needs_confirmation=body.needs_confirmation,
        anketa=body.anketa,
        failed=body.failed,
        blocked=body.blocked,
        bail_reason=body.bail_reason,
    )


@router.post("/pause", response_model=AutoApplyPauseResponse)
async def pause(
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyPauseResponse:
    """Kill switch (Фаза 7.4): мгновенно `enabled=False` на всех площадках разом.

    Общая ручка для веб-тумблера и `/pause_autoapply` в Telegram-боте — обе поверхности зовут
    её вместо того чтобы каждая сама грузила конфиг и гасила 3 флага.
    """
    config = await pause_all(account_id=account.account_id)
    return AutoApplyPauseResponse(config=config)


@router.post("/clear", response_model=AutoApplyClearResponse)
async def clear(
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyClearResponse:
    """Ручная очистка очереди (пункт 1 редизайна «Расширения»): пропустить разом всё, что сейчас
    видно в превью (auto + manual_review) по всем площадкам — не kill switch, площадки остаются
    в прежнем режиме, очередь просто пересчитается пустой на следующий запрос.
    """
    cleared = await clear_queue(account_id=account.account_id)
    return AutoApplyClearResponse(cleared=cleared)


@router.post("/manual-send", response_model=AutoApplyManualSendResponse)
async def manual_send(
    account: AccountContext = Depends(require_account_context),
) -> AutoApplyManualSendResponse:
    config = await get_auto_apply_config(account_id=account.account_id)
    any_enabled = any(getattr(config, p).enabled for p in ("hh", "getmatch", "habr"))
    if not any_enabled:
        raise to_http(InvalidInput("Нет включённых площадок автооткликов"))
    await set_manual_send_pending(True, account_id=account.account_id)
    event(
        logger,
        "АВТООТКЛИК",
        "ручная отправка запрошена (account_id=%s)",
        account.account_id,
        account_id=account.account_id,
    )
    return AutoApplyManualSendResponse(queued=True)


@router.post("/clear-manual-send", status_code=204)
async def clear_manual_send(
    account: AccountContext = Depends(require_account_context),
) -> None:
    await set_manual_send_pending(False, account_id=account.account_id)
    event(
        logger,
        "АВТООТКЛИК",
        "флаг ручной отправки снят (account_id=%s)",
        account.account_id,
        account_id=account.account_id,
    )


def _anketa_item(job: Job) -> AnketaPendingItem:
    return AnketaPendingItem(
        job_id=job.id or 0,
        vacancy_id=job.vacancy_id or "",
        url=job.url,
        title=job.title,
        company=job.company,
        cover_letter_text=job.cover_letter_text,
        anketa=AnketaState.model_validate(job.anketa),
    )


@router.get("/anketa/pending", response_model=AnketaPendingResponse)
async def anketa_pending(
    platform: AutoApplyPlatform,
    status: str = "pending",
    account: AccountContext = Depends(require_account_context),
) -> AnketaPendingResponse:
    """Вакансии с анкетой в заданном статусе (Фаза 3.3): `status=pending` — очередь
    подтверждения на доске/в дровере; `status=approved` — тем же путём раннер узнаёт, какие
    анкеты пора отправить по-настоящему на следующем тике."""
    jobs = await list_pending_anketas(platform, status=status, account_id=account.account_id)
    return AnketaPendingResponse(
        platform=platform, status=status, items=[_anketa_item(j) for j in jobs]
    )


@router.post("/anketa/{job_id}/confirm", response_model=AnketaPendingItem)
async def anketa_confirm(
    job_id: int,
    body: AnketaConfirmRequest,
    account: AccountContext = Depends(require_account_context),
) -> AnketaPendingItem:
    """Владелец подтверждает анкету (возможно отредактированные ответы) — `pending →
    approved`. Реальную отправку выполняет раннер на следующем тике, не этот запрос."""
    job = await confirm_anketa(job_id, answers=body.answers, account_id=account.account_id)
    if job is None:
        raise to_http(NotFound(f"анкета не найдена: job_id={job_id}"))
    return _anketa_item(job)


@router.post("/anketa/{job_id}/reject", response_model=AnketaPendingItem)
async def anketa_reject(
    job_id: int,
    account: AccountContext = Depends(require_account_context),
) -> AnketaPendingItem:
    """Владелец отклоняет анкету — `pending → rejected`, раннер её больше не подхватит."""
    job = await reject_anketa(job_id, account_id=account.account_id)
    if job is None:
        raise to_http(NotFound(f"анкета не найдена: job_id={job_id}"))
    return _anketa_item(job)
