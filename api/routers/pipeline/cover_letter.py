"""Короткое сопроводительное по вакансии: кнопка «Сгенерировать письмо» в карточке.

Кросс-доменный сценарий — `core.app.scenarios.cover_letter`. Ключ — числовой
`job.id` (как смена стадии / поля карточки), а не vacancy_id.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from api.errors import to_http
from api.schemas import CoverLetterRequest, CoverLetterResponse
from api.security import AccountContext, require_account_context
from core.app.scenarios.cover_letter import generate_for_job
from core.kernel.errors import DomainError

router = APIRouter(prefix="/api/jobs", tags=["cover-letter"])


@router.post("/{job_id}/cover-letter", response_model=CoverLetterResponse)
async def make_cover_letter(
    job_id: int,
    body: CoverLetterRequest | None = Body(default=None),
    account: AccountContext = Depends(require_account_context),
) -> CoverLetterResponse:
    """Сгенерировать сопроводительное под вакансию (LLM), записать в `jobs.cover_letter_text`.

    `body.lang` — переключалка RU/EN (Э4.4); без тела/без `lang` язык выводится из резюме.
    """
    lang = body.lang if body is not None else None
    try:
        result = await generate_for_job(job_id, account_id=account.account_id, lang=lang)
    except DomainError as exc:
        raise to_http(exc) from exc
    return CoverLetterResponse(**result.model_dump())
