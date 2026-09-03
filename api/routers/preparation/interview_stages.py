"""Цепочка этапов собеса по вакансии (`interview_stages` как первоклассный веб-объект).

Сценарии — `core.domains.preparation.scenarios`. Нет PG — GET деградирует до
пустого списка; мутации требуют PG (503).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.errors import to_http
from api.routers.preparation.mappers import stage_out, stages_list
from api.schemas import (
    InterviewStageCreate,
    InterviewStageListResponse,
    InterviewStageOut,
    InterviewStagePatch,
    InterviewStageReorderRequest,
)
from api.security import AccountContext, require_account_context
from core.domains.preparation import scenarios as prep
from core.kernel.errors import DomainError

router = APIRouter(prefix="/api/interview-stages", tags=["interview-stages"])


@router.get("/{vacancy_id}", response_model=InterviewStageListResponse)
async def list_stages(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> InterviewStageListResponse:
    """Цепочка этапов вакансии по порядку. Нет PG → пустой список."""
    return stages_list(
        vacancy_id, await prep.list_stages(vacancy_id, account_id=account.account_id)
    )


@router.post("/{vacancy_id}", response_model=InterviewStageOut)
async def create_stage(
    vacancy_id: str,
    body: InterviewStageCreate,
    account: AccountContext = Depends(require_account_context),
) -> InterviewStageOut:
    """Добавить этап из канона в конец цепочки."""
    try:
        saved = await prep.create_stage(
            vacancy_id,
            stage_type=body.stage_type,
            scheduled_at=body.scheduled_at,
            format=body.format,
            notes=body.notes.strip(),
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return stage_out(saved)


@router.patch("/{vacancy_id}/reorder", response_model=InterviewStageListResponse)
async def reorder(
    vacancy_id: str,
    body: InterviewStageReorderRequest,
    account: AccountContext = Depends(require_account_context),
) -> InterviewStageListResponse:
    """Переставить порядок цепочки (перетаскивание в UI)."""
    try:
        stages = await prep.reorder_stages(
            vacancy_id, body.ordered_ids, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return stages_list(vacancy_id, stages)


@router.patch("/{vacancy_id}/{stage_id}", response_model=InterviewStageOut)
async def patch_stage(
    vacancy_id: str,
    stage_id: int,
    body: InterviewStagePatch,
    account: AccountContext = Depends(require_account_context),
) -> InterviewStageOut:
    """Точечная правка этапа (дата/формат/статус/заметка)."""
    try:
        saved = await prep.patch_stage(
            vacancy_id,
            stage_id,
            body.model_dump(exclude_unset=True),
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return stage_out(saved)


@router.delete("/{vacancy_id}/{stage_id}", status_code=204, response_model=None)
async def remove_stage(
    vacancy_id: str, stage_id: int, account: AccountContext = Depends(require_account_context)
) -> None:
    """Убрать этап из цепочки."""
    try:
        await prep.remove_stage(vacancy_id, stage_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
