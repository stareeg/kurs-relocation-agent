"""Пропущенные вакансии — путь расширения (кнопка «Пропустить» / лента пропусков).

Источник истины — Postgres (`core.domains.opportunities.skipped`): "skip" —
решение «не подавать», ортогонально статусу воронки. зеркало воронки удалено.

`POST /skip` идёт через `service.skip_and_store` (не `skipped.save_skipped` напрямую) —
тонкая обёртка вокруг него же; в `jobs` пропуск ничего не пишет (см. skip_and_store).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.schemas import SkipDeleteResponse, SkipVacancyRequest
from api.security import AccountContext, require_account_context
from core.domains.opportunities.service import skip_and_store
from core.domains.opportunities.skip_reasons import canonical_skip_reason
from core.domains.opportunities.skipped import SkippedVacancy, delete_skipped, load_skipped_list
from core.domains.profile.company_normalize import (
    SKIP_REASON_DODGY_COMPANY,
    add_company_to_avoid,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["skipped"])


@router.get("/skipped", response_model=list[SkippedVacancy])
async def list_skipped(
    limit: int = 30, account: AccountContext = Depends(require_account_context)
) -> list[SkippedVacancy]:
    """Последние пропущенные вакансии из Postgres (источник истины)."""
    try:
        return await load_skipped_list(limit=min(limit, 100), account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая лента, не 500
        logger.debug("skipped-список: Postgres недоступен: %s", exc)
        return []


@router.post("/skip", response_model=SkippedVacancy)
async def skip_vacancy(
    body: SkipVacancyRequest,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> SkippedVacancy:
    """Ручная фиксация пропуска (без повторного скоринга). Postgres — источник истины.

    `skip_reason` — сырой текст (LLM-чип или статичный лейбл); `canonical_reason`
    нормализуется через `canonical_skip_reason` для аналитики/грид-метрик.
    """
    canonical = canonical_skip_reason(body.skip_reason)
    try:
        record = await skip_and_store(
            body.vacancy_id,
            body.skip_reason,
            url=body.url,
            title=body.title,
            company=body.company,
            overall_score=body.overall_score,
            recommendation=body.recommendation,
            account_id=account.account_id,
            canonical_reason=canonical,
        )
    except Exception as exc:  # noqa: BLE001 — без PG пропуск не зафиксировать (источник истины)
        logger.error("skip: запись в Postgres не удалась: %s", exc)
        raise HTTPException(status_code=503, detail="Postgres недоступен") from exc

    # Избегать компанию → в список «Избегать» резюме (фоном: LLM-нормализация не
    # должна держать ответ skip; ошибка внутри не ломает сам пропуск). Срабатывает
    # по канонической причине — работает и для LLM-чипа, и для статичной кнопки,
    # и для legacy-строки «Сомнительная компания» (через canonical_skip_reason).
    if canonical == SKIP_REASON_DODGY_COMPANY and body.company:
        background.add_task(add_company_to_avoid, body.company, account_id=account.account_id)

    return record


@router.delete("/skip/{vacancy_id}", response_model=SkipDeleteResponse)
async def unskip_vacancy(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> SkipDeleteResponse:
    """Снять пропуск (вернуть вакансию в воронку). Решение «не подавать» отменяемо.

    Нужно, чтобы пропуск не был вечным тупиком: вакансия, попавшая в «Пропущено» (в т.ч.
    исторически авто-записанная по recommendation=skip до фикса persist.py), возвращается
    в активный путь одним кликом из расширения/веба.
    """
    try:
        removed = await delete_skipped(vacancy_id, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — без PG не снять пропуск (источник истины)
        logger.error("unskip: запись в Postgres не удалась: %s", exc)
        raise HTTPException(status_code=503, detail="Postgres недоступен") from exc

    return SkipDeleteResponse(vacancy_id=vacancy_id, skipped=False, removed=removed)
