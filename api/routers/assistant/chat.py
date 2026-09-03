"""Прямой SSE-стрим чата: роутер отдаёт токены из `assistant.stream_answer` как есть."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.schemas import ChatStreamRequest
from api.security import AccountContext, require_account_context
from api.streaming import sse_response
from core.domains.assistant import stream_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


async def _chat_payloads(payload: dict, *, account_id: int) -> AsyncIterator[dict[str, Any]]:
    """Доменный ``{event, data}`` → payload с ``type`` для единого SSE-контракта."""
    try:
        async for ev in stream_answer(payload, account_id=account_id):
            data = dict(ev.get("data") or {})
            data["type"] = str(ev["event"])
            yield data
    except Exception as exc:  # noqa: BLE001 — не роняем SSE без финального done
        logger.exception("chat/stream: необработанная ошибка: %s", exc)
        yield {"type": "error", "message": str(exc)}
        yield {"type": "done", "status": "error"}


@router.post("/chat/stream")
async def chat_stream(
    body: ChatStreamRequest, account: AccountContext = Depends(require_account_context)
) -> StreamingResponse:
    """SSE: part(token|result) → done (или error → done)."""
    return sse_response(
        _chat_payloads(body.model_dump(exclude_none=False), account_id=account.account_id)
    )
