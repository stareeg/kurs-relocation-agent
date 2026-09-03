"""Статус воронки — путь расширения (кнопки «Отметить отклик» / «Оффер», бейдж статуса).

Источник истины — Postgres (`jobs.status` + история `application_stages`), как и `/score`.
Легаси SQLite и зеркало воронки удалено в воронке больше не участвуют.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.errors import to_http
from api.schemas import FunnelStatusResponse, FunnelStatusUpdate
from api.security import AccountContext, require_account_context
from core.domains.opportunities.service import get_funnel_snapshot, set_funnel_status
from core.kernel.errors import DomainError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["funnel"])


@router.get("/funnel/{vacancy_id}", response_model=FunnelStatusResponse)
async def get_funnel_status(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> FunnelStatusResponse:
    """Текущий статус воронки + флаг пропуска (и его причина) из Postgres (источник истины)."""
    try:
        snapshot = await get_funnel_snapshot(vacancy_id, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → статус неизвестен, не 500
        logger.debug("funnel-чтение: Postgres недоступен: %s", exc)
        return FunnelStatusResponse(vacancy_id=vacancy_id)
    return FunnelStatusResponse(
        vacancy_id=vacancy_id,
        status=snapshot.status,
        source="db" if snapshot.status else None,
        skipped=snapshot.skipped,
        skip_reason=snapshot.skip_reason,
    )


@router.post("/funnel", response_model=FunnelStatusResponse)
async def update_funnel_status(
    body: FunnelStatusUpdate, account: AccountContext = Depends(require_account_context)
) -> FunnelStatusResponse:
    """Сменить статус воронки в Postgres (источник истины).

    Неизвестный статус → 400, нет PG → 503.
    """
    try:
        status, job_id = await set_funnel_status(
            body.vacancy_id,
            body.status,
            cover_letter=body.cover_letter,
            published_at=body.published_at,
            title=body.title,
            company=body.company,
            vacancy_text=body.vacancy_text,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return FunnelStatusResponse(
        vacancy_id=body.vacancy_id, status=status, source="db", job_id=job_id
    )
