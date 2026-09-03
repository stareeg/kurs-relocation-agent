"""Реестр компаний для доски «Рынок → Компании».

Сценарий — `core.app.scenarios.companies`: агрегаты jobs + вердикт из резюме.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.routers.opportunities.mappers import company_registry_response
from api.schemas import CompanyRegistryResponse
from api.security import AccountContext, require_account_context
from core.app.scenarios.companies import list_registry

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("", response_model=CompanyRegistryResponse)
async def get_companies(
    account: AccountContext = Depends(require_account_context),
) -> CompanyRegistryResponse:
    """Полный реестр компаний: count, avg, best_stage, verdict из резюме."""
    return company_registry_response(await list_registry(account_id=account.account_id))
