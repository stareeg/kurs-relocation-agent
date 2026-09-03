"""Трек поиска: `GET/PATCH /api/career/track` — вторая работа рядом с основной.

Тонкий роутер: валидация → `career.track_state` → ответ. Основной трек тумблером
не выключается — продуктовая ручка одна (`second_job_enabled`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.schemas import SearchTrackOut, SearchTrackPatch
from api.security import AccountContext, require_account_context
from core.domains.career import track_state

router = APIRouter(prefix="/api/career", tags=["career"])


@router.get("/track", response_model=SearchTrackOut)
async def get_search_track(
    account: AccountContext = Depends(require_account_context),
) -> SearchTrackOut:
    state = await track_state.get_current_tracks(account_id=account.account_id)
    return SearchTrackOut.model_validate(state.model_dump())


@router.patch("/track", response_model=SearchTrackOut)
async def patch_search_track(
    body: SearchTrackPatch,
    account: AccountContext = Depends(require_account_context),
) -> SearchTrackOut:
    await track_state.set_second_job_enabled(
        body.second_job_enabled,
        account_id=account.account_id,
        actor=body.actor,
        reason=body.reason,
    )
    state = await track_state.get_current_tracks(account_id=account.account_id)
    return SearchTrackOut.model_validate(state.model_dump())
