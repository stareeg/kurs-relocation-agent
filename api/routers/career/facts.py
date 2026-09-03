"""Долгая память под управлением владельца — `GET/PATCH/DELETE /api/career/facts` (Э9.4).

`career_facts` реально читаются чатом и подготовкой (`load_facts_context_block`), но владелец
не мог ни увидеть, что система о нём «помнит», ни поправить, ни удалить неверный факт.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.schemas import CareerFactPatch
from api.security import AccountContext, require_account_context
from core.domains.career.models import CareerFact
from core.domains.career.repo import delete_fact, list_active_facts, update_fact

router = APIRouter(prefix="/api/career", tags=["career"])


@router.get("/facts", response_model=list[CareerFact])
async def facts_list(
    type: str | None = Query(default=None, alias="type"),
    source: str | None = Query(default=None, alias="source"),
    account: AccountContext = Depends(require_account_context),
) -> list[CareerFact]:
    """Активные факты аккаунта (не протухшие), опционально по виду/источнику."""
    return await list_active_facts(
        account_id=account.account_id, fact_type=type, source_kind=source
    )


@router.patch("/facts/{fact_id}", response_model=CareerFact)
async def facts_patch(
    fact_id: int,
    body: CareerFactPatch,
    account: AccountContext = Depends(require_account_context),
) -> CareerFact:
    """Поправить текст и/или закрепить факт. 404 — факта нет/чужой."""
    result = await update_fact(
        fact_id, account_id=account.account_id, fact=body.fact, pinned=body.pinned
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Факт не найден")
    return result


@router.delete("/facts/{fact_id}")
async def facts_delete(
    fact_id: int,
    account: AccountContext = Depends(require_account_context),
) -> dict[str, bool]:
    """Удалить неверный факт. 404 — факта нет/чужой."""
    removed = await delete_fact(fact_id, account_id=account.account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Факт не найден")
    return {"deleted": True}
