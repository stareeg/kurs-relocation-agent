"""SSE-канал доменных событий: фронт подписывается вместо `refetchInterval`-поллинга.

Соединение живёт, пока открыта вкладка (без терминального `done`); каждое доменное событие
шины приходит кадром `part` с `data.type` = имя события (`VacancyScored`,
`ApplicationStageChanged`, …) — фронт сам решает, какие query keys инвалидировать.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.security import AccountContext, require_account_context
from api.streaming import sse_response
from core.platform.events.live import broadcaster

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events/stream")
async def events_stream(
    account: AccountContext = Depends(require_account_context),
) -> StreamingResponse:
    """SSE: живая лента доменных событий СВОЕГО аккаунта для инвалидации кэша
    react-query на фронте (раньше события всех аккаунтов уходили всем вкладкам)."""
    queue = broadcaster.register(account.account_id)
    return sse_response(broadcaster.stream(queue))
