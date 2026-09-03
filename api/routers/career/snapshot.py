"""Снимок «Где я сейчас» + дельта «Что изменилось».

`GET /api/career/snapshot` (Э9.2) и `GET /api/career/delta` (Э9.5).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.security import AccountContext, require_account_context
from core.app.scenarios.career_delta import CareerDelta, career_delta
from core.app.scenarios.career_snapshot import CareerSnapshot, career_snapshot

router = APIRouter(prefix="/api/career", tags=["career"])


@router.get("/snapshot", response_model=CareerSnapshot)
async def get_career_snapshot(
    account: AccountContext = Depends(require_account_context),
) -> CareerSnapshot:
    return await career_snapshot(account_id=account.account_id)


@router.get("/delta", response_model=CareerDelta | None)
async def get_career_delta(
    account: AccountContext = Depends(require_account_context),
) -> CareerDelta | None:
    return await career_delta(account_id=account.account_id)
