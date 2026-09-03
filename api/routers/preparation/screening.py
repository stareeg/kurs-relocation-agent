"""Раздел «Скрининги»: канонический пакет под вакансию.

Сценарии — `core.domains.preparation.screening.scenarios`; сборка пакета внутри —
`Pipeline`. Роутер — валидация, вызов, SSE/JSON транспорт.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.errors import to_http
from api.routers.preparation.mappers import screening_pack, screening_sse_payloads
from api.schemas import (
    SavedScreeningQuestions,
    ScreeningDeleteQuestionRequest,
    ScreeningMoreQuestionsRequest,
    ScreeningPitchEditRequest,
    ScreeningQuestionsRequest,
    TelegramPushResponse,
)
from api.security import AccountContext, require_account_context
from api.streaming import sse_response, wants_sse
from core.app.scenarios.prep_chat import load_history
from core.domains.opportunities.jobs import get_job_by_vacancy_id
from core.domains.preparation.screening import scenarios as screening
from core.domains.preparation.screening.chat_summary import summarize_screening_chat
from core.domains.profile import telegram_push as tg_push
from core.kernel.errors import DomainError
from core.platform.repo.accounts import get_account_by_telegram_user_id

router = APIRouter(prefix="/api/screening", tags=["screening"])


def _sse_stream(
    vacancy_id: str, body: ScreeningQuestionsRequest, *, account_id: int
) -> StreamingResponse:
    return sse_response(
        screening_sse_payloads(
            screening.stream_pack(
                vacancy_id,
                title=body.title,
                company=body.company,
                vacancy_text=body.vacancy_text,
                account_id=account_id,
            )
        )
    )


@router.get("/{vacancy_id}", response_model=SavedScreeningQuestions)
async def get_screening_questions_endpoint(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> SavedScreeningQuestions:
    """Сохранённый пакет под вакансию. Нет записи/нет PG → пустой ответ."""
    saved = await screening.load_pack(vacancy_id, account_id=account.account_id)
    if saved is None:
        return SavedScreeningQuestions(vacancy_id=vacancy_id, groups=[])
    return screening_pack(saved)


@router.post("/{vacancy_id}/generate", response_model=SavedScreeningQuestions)
async def generate_screening_questions_endpoint(
    vacancy_id: str,
    body: ScreeningQuestionsRequest,
    request: Request,
    account: AccountContext = Depends(require_account_context),
) -> SavedScreeningQuestions | StreamingResponse:
    """Сгенерировать пакет и сохранить. `Accept: text/event-stream` → поток событий."""
    if wants_sse(request.headers.get("accept")):
        return _sse_stream(vacancy_id, body, account_id=account.account_id)
    try:
        pack = await screening.generate_pack(
            vacancy_id,
            title=body.title,
            company=body.company,
            vacancy_text=body.vacancy_text,
            account_id=account.account_id,
        )
        saved = await screening.persist_pack(vacancy_id, pack, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return screening_pack(saved)


@router.post("/{vacancy_id}/regen-pitch", response_model=SavedScreeningQuestions)
async def regen_screening_pitch_endpoint(
    vacancy_id: str,
    body: ScreeningQuestionsRequest,
    account: AccountContext = Depends(require_account_context),
) -> SavedScreeningQuestions:
    """Пересобрать только легенду/мосты, вопросы не трогать."""
    try:
        updated = await screening.regenerate_pitch(
            vacancy_id,
            title=body.title,
            company=body.company,
            vacancy_text=body.vacancy_text,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return screening_pack(updated)


@router.patch("/{vacancy_id}/pitch", response_model=SavedScreeningQuestions)
async def edit_screening_pitch_endpoint(
    vacancy_id: str,
    body: ScreeningPitchEditRequest,
    account: AccountContext = Depends(require_account_context),
) -> SavedScreeningQuestions:
    """Ручная правка «Рассказа об опыте» (закреплённое сообщение в чате Скринингов, п.2)."""
    try:
        updated = await screening.edit_pitch_manual(
            vacancy_id, oral_pitch=body.oral_pitch, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return screening_pack(updated)


@router.post("/{vacancy_id}/more-questions", response_model=SavedScreeningQuestions)
async def more_screening_questions_endpoint(
    vacancy_id: str,
    body: ScreeningMoreQuestionsRequest,
    account: AccountContext = Depends(require_account_context),
) -> SavedScreeningQuestions:
    """Дописать ещё пачку вопросов (hr|ask) без пересборки легенды."""
    try:
        updated = await screening.more_questions(
            vacancy_id,
            kind=body.kind,
            title=body.title,
            company=body.company,
            count=body.count,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return screening_pack(updated)


@router.post("/{vacancy_id}/delete-question", response_model=SavedScreeningQuestions)
async def delete_screening_question_endpoint(
    vacancy_id: str,
    body: ScreeningDeleteQuestionRequest,
    account: AccountContext = Depends(require_account_context),
) -> SavedScreeningQuestions:
    """Удалить один вопрос (hr|ask) из собранного пакета, легенду не трогать."""
    try:
        updated = await screening.delete_question(
            vacancy_id,
            kind=body.kind,
            question=body.question,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return screening_pack(updated)


async def _push_chat_summary(vacancy_id: str, *, account: AccountContext) -> TelegramPushResponse:
    """Саммари переписки «Агент»-чата (LLM, на клике) → пуш в Telegram-бота — продолжить разговор
    про вакансию там. Валидация «своя вакансия» — как у общего `/api/telegram/push`
    (`api/routers/meta/telegram.py::enqueue_push_response`)."""
    caller = await get_account_by_telegram_user_id(account.telegram_user_id)
    if caller is None:
        raise HTTPException(status_code=409, detail="Сначала войдите токеном из бота (Параметры)")

    vid = vacancy_id.strip()
    job = await get_job_by_vacancy_id(vid, account_id=caller.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")

    history = await load_history(vid, account_id=caller.id)
    messages = [(m.role, m.content) for m in history]
    summary = await summarize_screening_chat(
        messages, account_id=caller.id, title=job.title or "", company=job.company or ""
    )

    task = await tg_push.enqueue_tg_push(
        "screening_chat_summary", vid, account_id=caller.id, text=summary
    )
    return TelegramPushResponse(
        queued=True, task_id=task.id, kind="screening_chat_summary", vacancy_id=vid
    )


@router.post("/{vacancy_id}/chat-summary-push", response_model=TelegramPushResponse)
async def push_chat_summary_endpoint(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> TelegramPushResponse:
    """Саммари переписки «Агент»-чата → пуш в Telegram-бота."""
    return await _push_chat_summary(vacancy_id, account=account)
