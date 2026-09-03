"""Синхронизация откликов hh.ru → статусы воронки (страница «Мои отклики» в расширении).

`POST /funnel/negotiations-preview` — текущий vs предлагаемый статус для списка откликов;
`POST /funnel/sync-negotiations` — применить (Postgres), `…/stream` — то же с NDJSON.

Схемы (`core.domains.offers.hh_negotiations`) — чистый pydantic, импортируем в топе для валидации/OpenAPI.
Логика (`core.domains.pipeline.negotiations`) пишет стадии в Postgres — импорт ленивый,
внутри хендлера (чтобы роутер импортился без backend на path).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.security import AccountContext, require_account_context
from core.domains.offers.hh_negotiations import (
    NegotiationsPreviewRequest,
    NegotiationsPreviewResponse,
    SyncNegotiationsRequest,
    SyncNegotiationsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["negotiations"])


def _import_sync():
    """Ленивый импорт core-логики; 503, если модуль недоступен."""
    try:
        from core.domains.pipeline.negotiations import (
            preview_negotiations,
            sync_negotiations_batch,
            sync_negotiations_batch_stream,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Синхронизация откликов недоступна: %s", exc)
        raise HTTPException(status_code=503, detail="Синхронизация откликов недоступна") from exc
    return preview_negotiations, sync_negotiations_batch, sync_negotiations_batch_stream


@router.post("/funnel/negotiations-preview", response_model=NegotiationsPreviewResponse)
async def negotiations_preview(
    body: NegotiationsPreviewRequest,
    account: AccountContext = Depends(require_account_context),
) -> NegotiationsPreviewResponse:
    """Текущий vs предлагаемый статус для списка откликов (без записи)."""
    preview_negotiations, _, _ = _import_sync()
    return await preview_negotiations(body.items, account_id=account.account_id)


@router.post("/funnel/sync-negotiations", response_model=SyncNegotiationsResponse)
async def sync_negotiations(
    body: SyncNegotiationsRequest, account: AccountContext = Depends(require_account_context)
) -> SyncNegotiationsResponse:
    """Применить статусы из hh.ru/negotiations → Postgres."""
    if not body.items:
        return SyncNegotiationsResponse(results=[], synced_count=0, skipped_count=0)
    _, sync_negotiations_batch, _ = _import_sync()
    return await sync_negotiations_batch(
        body.items,
        dry_run=body.dry_run,
        use_llm=body.use_llm,
        force=body.force,
        account_id=account.account_id,
    )


@router.post("/funnel/sync-negotiations/stream")
async def sync_negotiations_stream(
    body: SyncNegotiationsRequest, account: AccountContext = Depends(require_account_context)
) -> StreamingResponse:
    """SSE-стрим прогресса синхронизации (UI расширения слушает кадры)."""
    from api.streaming import sse_response

    _, _, sync_negotiations_batch_stream = _import_sync()
    return sse_response(
        sync_negotiations_batch_stream(
            body.items,
            dry_run=body.dry_run,
            use_llm=body.use_llm,
            force=body.force,
            account_id=account.account_id,
        )
    )
