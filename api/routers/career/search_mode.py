"""Режим поиска: `GET/PATCH /api/career/search-mode` — первый роутер домена career.

Режим — личная сущность аккаунта, которую читают советующие поверхности (метрики, ситуация,
дайджест — подключаются в ST-03). Переход пишется в `search_state_log`, публикует
`SearchModeChanged` (журнал СОБЫТИЕ + строка в `career_timeline` по подписке) и переживает
рестарт. Сама система режим не переключает — `actor="suggestion"` ставит владелец, принимая
предложение из очереди.

M5 (plans/multitenancy_gaps_2026_08_06.md §3.7): `require_account_context` — раньше
режим был один на всю систему, переключение одним другом меняло его всем (S2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.schemas import SearchModeOut, SearchModePatch
from api.security import AccountContext, require_account_context
from core.domains.career import search_state

router = APIRouter(prefix="/api/career", tags=["career"])


@router.get("/search-mode", response_model=SearchModeOut)
async def get_search_mode(
    account: AccountContext = Depends(require_account_context),
) -> SearchModeOut:
    state = await search_state.get_current_state(account_id=account.account_id)
    return SearchModeOut(mode=state.mode, label=state.label, since=state.since)


@router.patch("/search-mode", response_model=SearchModeOut)
async def patch_search_mode(
    body: SearchModePatch,
    account: AccountContext = Depends(require_account_context),
) -> SearchModeOut:
    entry = await search_state.set_search_mode(
        body.mode, account_id=account.account_id, actor=body.actor, reason=body.reason
    )
    return SearchModeOut(
        mode=entry.mode,
        label=search_state.mode_label(entry.mode),
        since=entry.created_at,
    )
