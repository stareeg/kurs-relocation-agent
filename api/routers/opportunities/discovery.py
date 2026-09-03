"""Живой статус + управление сессией discovery (авто-открытие вакансий расширением).

Конфиг (search_urls/batch_size/daily_cap) — через `GET/PATCH /api/settings` (`discovery_config`),
как и `auto_apply_config` — не здесь (см. api/routers/profile/settings.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.errors import to_http
from api.schemas import (
    DiscoveryEventRemoveRequest,
    DiscoveryPlatform,
    DiscoverySessionRequest,
    DiscoveryStatus,
    DiscoveryTickReport,
    DiscoveryTickRequest,
)
from api.security import AccountContext, require_account_context
from core.domains.opportunities.discovery_session import (
    clear_events,
    get_discovery_status,
    pause_session,
    remove_event,
    report_tick,
    report_tick_summary,
    resume_session,
    start_session,
    stop_session,
)
from core.kernel.errors import DomainError

router = APIRouter(prefix="/api/opportunities/discovery", tags=["discovery"])


@router.get("/status", response_model=DiscoveryStatus)
async def status(
    platform: DiscoveryPlatform,
    account: AccountContext = Depends(require_account_context),
) -> DiscoveryStatus:
    """Живой статус сессии одной площадки — для левой панели «Расширения»."""
    return await get_discovery_status(platform, account_id=account.account_id)


@router.post("/session", response_model=DiscoveryStatus)
async def session(
    platform: DiscoveryPlatform,
    body: DiscoverySessionRequest,
    account: AccountContext = Depends(require_account_context),
) -> DiscoveryStatus:
    """Старт/пауза/возобновление/стоп сессии — управляется владельцем из веба."""
    try:
        if body.action == "start":
            return await start_session(platform, account_id=account.account_id)
        if body.action == "pause":
            return await pause_session(platform, account_id=account.account_id, reason=body.reason)
        if body.action == "resume":
            return await resume_session(platform, account_id=account.account_id)
        if body.action == "clear":
            return await clear_events(platform, account_id=account.account_id)
        return await stop_session(platform, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc


@router.post("/remove-event", response_model=DiscoveryStatus)
async def remove_event_endpoint(
    platform: DiscoveryPlatform,
    body: DiscoveryEventRemoveRequest,
    account: AccountContext = Depends(require_account_context),
) -> DiscoveryStatus:
    """Кнопка «Удалить» на сломанной вакансии в логе «Просмотра» — убирает одну строку."""
    return await remove_event(platform, vacancy_id=body.vacancy_id, account_id=account.account_id)


@router.post("/tick", response_model=DiscoveryStatus)
async def tick(
    platform: DiscoveryPlatform,
    body: DiscoveryTickRequest,
    account: AccountContext = Depends(require_account_context),
) -> DiscoveryStatus:
    """Раннер расширения репортит исход одной открытой вакансии за тик."""
    return await report_tick(
        platform,
        account_id=account.account_id,
        vacancy_id=body.vacancy_id,
        outcome=body.outcome,
        title=body.title,
        company=body.company,
        pages_visited=body.pages_visited,
    )


@router.post("/tick-report", status_code=204)
async def tick_report(
    body: DiscoveryTickReport,
    account: AccountContext = Depends(require_account_context),
) -> None:
    """Итог тика раннера автопросмотра (heartbeat) — одна строка АВТОПРОСМОТР + `last_tick`."""
    await report_tick_summary(
        account_id=account.account_id,
        platforms_running=body.platforms_running,
        opened=body.opened,
        scored=body.scored,
        already_known=body.already_known,
        parse_errors=body.parse_errors,
        paused=body.paused,
        bail_reason=body.bail_reason,
    )
