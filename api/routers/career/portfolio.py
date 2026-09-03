"""Портфолио — `/api/career/portfolio` (A-24): элементы + черновики из резюме/разбора/оффера.

Этап 5.0 редизайна «Карьеры» (plans/career_redesign_2026_08_26.md) добавил `DELETE` — до этого
домен умел только создавать (вручную или черновиком) и читать; предпосылка нужна была под
Этап 5.2 (авто-черновик по событию сразу как обычная запись — без него неверную карточку
нечем было убрать).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import (
    PortfolioDraftFromDebriefRequest,
    PortfolioDraftFromOfferRequest,
    PortfolioItemCreate,
)
from api.security import AccountContext, require_account_context
from core.domains.career.models import PortfolioItem
from core.domains.career.portfolio import (
    draft_portfolio_from_debrief,
    draft_portfolio_from_offer,
    draft_portfolio_from_resume,
    persist_portfolio_items,
)
from core.domains.career.repo import delete_portfolio_item, list_portfolio_items
from core.domains.profile.structured_store import read_resume_data_for_account

router = APIRouter(prefix="/api/career/portfolio", tags=["career"])


@router.get("", response_model=list[PortfolioItem])
async def portfolio_list(
    account: AccountContext = Depends(require_account_context),
) -> list[PortfolioItem]:
    """Все элементы портфолио аккаунта (свежие первыми)."""
    return await list_portfolio_items(account_id=account.account_id)


@router.post("", response_model=PortfolioItem)
async def portfolio_create(
    body: PortfolioItemCreate, account: AccountContext = Depends(require_account_context)
) -> PortfolioItem:
    """Добавить элемент портфолио вручную."""
    saved = await persist_portfolio_items(
        [PortfolioItem(**body.model_dump())], account_id=account.account_id
    )
    return saved[0]


@router.post("/draft-from-resume", response_model=list[PortfolioItem])
async def portfolio_draft_from_resume(
    account: AccountContext = Depends(require_account_context),
) -> list[PortfolioItem]:
    """Черновик из опыта резюме: один элемент на блок ``experience``."""
    resume = await read_resume_data_for_account(account.account_id)
    drafts = draft_portfolio_from_resume(resume)
    return await persist_portfolio_items(drafts, account_id=account.account_id)


@router.post("/draft-from-debrief", response_model=list[PortfolioItem])
async def portfolio_draft_from_debrief(
    body: PortfolioDraftFromDebriefRequest,
    account: AccountContext = Depends(require_account_context),
) -> list[PortfolioItem]:
    """Черновик из разбора собеса: сильные ответы + summary."""
    drafts = draft_portfolio_from_debrief(**body.model_dump())
    return await persist_portfolio_items(drafts, account_id=account.account_id)


@router.post("/draft-from-offer", response_model=list[PortfolioItem])
async def portfolio_draft_from_offer(
    body: PortfolioDraftFromOfferRequest,
    account: AccountContext = Depends(require_account_context),
) -> list[PortfolioItem]:
    """Черновик из оффера/торга: вилка + аргументы как outcome."""
    drafts = draft_portfolio_from_offer(**body.model_dump())
    return await persist_portfolio_items(drafts, account_id=account.account_id)


@router.delete("/{item_id}")
async def portfolio_delete(
    item_id: int, account: AccountContext = Depends(require_account_context)
) -> dict[str, bool]:
    """Удалить элемент портфолио — например, неверный авто-черновик из разбора/оффера (5.2).
    404 — элемента нет/чужой."""
    removed = await delete_portfolio_item(item_id, account_id=account.account_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Элемент портфолио не найден")
    return {"deleted": True}
