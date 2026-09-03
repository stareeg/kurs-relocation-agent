"""Q&A по вакансии — путь расширения (чат «Вопросы по вакансии»).

Сценарий — `core.app.scenarios.vacancy_ask`. Бейдж «уже смотрели» — тонкое чтение
`opportunities.jobs`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.errors import to_http
from api.schemas import (
    ScoreResponse,
    ScoreThesesUpdate,
    VacancyAskRequest,
    VacancyAskResponse,
    VacancySeenResponse,
    VacancyTextFormatResponse,
)
from api.security import AccountContext, require_account_context
from core.app.scenarios.vacancy_ask import ask
from core.domains.assistant.models import AskMessage
from core.kernel.errors import DomainError, LlmError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["vacancies"])


@router.get("/vacancies/{vacancy_id}/seen", response_model=VacancySeenResponse)
async def vacancy_seen(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> VacancySeenResponse:
    """Бейдж «уже смотрели»: оценивалась ли вакансия (Postgres — источник истины)."""
    from core.domains.opportunities.jobs import get_job_by_vacancy_id

    try:
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → бейдж не критичен
        logger.debug("seen: Postgres недоступен: %s", exc)
        return VacancySeenResponse(vacancy_id=vacancy_id)
    return VacancySeenResponse(
        vacancy_id=vacancy_id, seen=job is not None, source="db" if job is not None else None
    )


@router.get("/vacancies/{vacancy_id}/record", response_model=ScoreResponse)
async def vacancy_record(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> ScoreResponse:
    """Полная запись проскоренной вакансии для авто-разворота в расширении.

    Когда пользователь открывает уже проскоренную вакансию, но локального кэша
    расширения нет (новая вкладка / очищен storage), расширение тянет запись
    отсюда и сразу показывает результаты скоринга — без кнопки «Оценить ещё раз».
    404 если вакансии нет в системе или у неё нет скоринга (для авто-разворота
    бесполезна — расширение пойдёт на автоскоринг).
    """
    from api.routers.opportunities.mappers import job_to_score_response
    from core.domains.opportunities.jobs import get_job_by_vacancy_id

    job = await get_job_by_vacancy_id(vacancy_id, account_id=account.account_id)
    if job is None or not job.score:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    return job_to_score_response(job)


@router.patch("/vacancies/{vacancy_id}/score/theses", response_model=ScoreResponse)
async def update_vacancy_theses(
    vacancy_id: str,
    body: ScoreThesesUpdate,
    account: AccountContext = Depends(require_account_context),
) -> ScoreResponse:
    """Ручная правка тезисов скора (расширение, Решение 3): drag-and-drop тезиса между Плюсы/
    Минусы/Красные флаги + удаление — всегда шлём все три списка целиком. Не пересчёт скора,
    только точечная правка списков поверх уже посчитанного (см. `update_job_theses`).
    """
    from api.routers.opportunities.mappers import job_to_score_response
    from core.domains.opportunities.jobs import update_job_theses

    job = await update_job_theses(
        vacancy_id,
        pros=body.pros,
        cons=body.cons,
        red_flags=body.red_flags,
        account_id=account.account_id,
    )
    if job is None or not job.score:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    return job_to_score_response(job)


@router.get("/api/vacancies/{vacancy_id}/text-format", response_model=VacancyTextFormatResponse)
async def vacancy_text_format(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> VacancyTextFormatResponse:
    """Текст вакансии с абзацами и **выделениями** для дровера (веб). Дешёвый extract-вызов,
    результат кэшируется бэкендом по тексту — повторные открытия дровера не бьют LLM снова.

    Деградирует: нет вакансии/текста/LLM — пустая строка, фронт остаётся на сыром тексте.
    """
    from core.domains.opportunities.jobs import get_job_by_vacancy_id
    from core.domains.opportunities.text_format import format_vacancy_text

    job = await get_job_by_vacancy_id(vacancy_id, account_id=account.account_id)
    if job is None or not (job.vacancy_text or "").strip():
        return VacancyTextFormatResponse(vacancy_id=vacancy_id, formatted="")
    try:
        formatted = await format_vacancy_text(job.vacancy_text)
    except LlmError as exc:
        logger.debug("text-format: LLM недоступен для %s: %s", vacancy_id, exc)
        return VacancyTextFormatResponse(vacancy_id=vacancy_id, formatted="")
    return VacancyTextFormatResponse(vacancy_id=vacancy_id, formatted=formatted)


@router.post("/vacancies/{vacancy_id}/ask", response_model=VacancyAskResponse)
async def ask_vacancy(
    vacancy_id: str,
    body: VacancyAskRequest,
    account: AccountContext = Depends(require_account_context),
) -> VacancyAskResponse:
    """Ответ LLM по конкретной вакансии с учётом текста, оценки и резюме кандидата."""
    history = [AskMessage(role=m.role, content=m.content) for m in body.history]
    try:
        result = await ask(
            vacancy_id,
            question=body.question,
            vacancy_text=body.vacancy_text,
            title=body.title,
            company=body.company,
            salary_text=body.salary_text,
            score=body.score,
            history=history,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return VacancyAskResponse(**result.model_dump())
