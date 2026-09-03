"""Разговоры по вакансии: единая лента HR-переписки + уточняющего LLM-чата.

Один разговор = один тред (`hr_threads`), ключ — `vacancy_id`. Реплики (`hr_messages`) помечены
типом `kind` (hr_in / hr_out / llm_user / llm_assistant) — так в одной ленте видно и реальную
переписку с рекрутером, и болтовню с ассистентом, не путая их. Источники чата (карточка веба,
расширение) пишут в ОДИН разговор вакансии — чаты по вакансии больше не плодятся.

Сборка разговора кросс-доменная (pipeline + opportunities + preparation), поэтому живёт в
`core.app.scenarios.conversations`. Роутер — валидация, вызов сценария, маппинг ошибки;
проекции в схемы — в `mappers.py`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.errors import to_http
from api.routers.assistant.mappers import (
    attention_out,
    conversation_identity_out,
    conversation_list,
    conversation_out,
    thread_out,
)
from api.schemas import (
    ConversationIdentityRequest,
    ConversationIdentityResult,
    ConversationImportRequest,
    ConversationImportResult,
    ConversationList,
    ConversationMessageIn,
    ConversationOut,
    ConversationOutreachRequest,
    ConversationOutreachResult,
    ConversationVacancyTextRequest,
    ConversationVacancyTextResult,
    FunnelSuggestionApplyResult,
    FunnelSuggestionDismissResult,
    HrThreadOut,
    HrThreadUpdate,
    TodayAttention,
    VacancyAttachSuggestionOut,
    VacancyAttachSuggestRequest,
    VacancyAttachSuggestResult,
)
from api.security import AccountContext, require_account_context
from core.app.scenarios.conversations import (
    NO_STORE,
    add_conversation_message,
    attach_vacancy_text_and_rescore,
    create_outreach,
    delete_conversation_message,
    import_correspondence,
    load_attention,
    load_conversation,
    on_incoming_hr_message,
    open_conversation,
    suggest_attach,
    update_conversation,
    update_vacancy_identity_and_rescore,
)
from core.kernel.errors import DomainError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.post("/suggest-attach", response_model=VacancyAttachSuggestResult)
async def conversation_suggest_attach(
    body: VacancyAttachSuggestRequest,
    account: AccountContext = Depends(require_account_context),
) -> VacancyAttachSuggestResult:
    """По дампу/черновику предложить привязку к известной вакансии (без LLM, детерминированно)."""
    found = await suggest_attach(
        body.text,
        company=body.company,
        vacancy_url=body.vacancy_url,
        account_id=account.account_id,
    )
    outs = [VacancyAttachSuggestionOut.model_validate(c.model_dump()) for c in found]
    return VacancyAttachSuggestResult(
        suggestion=outs[0] if len(outs) == 1 else None, candidates=outs
    )


@router.post("/outreach", response_model=ConversationOutreachResult)
async def conversation_outreach(
    body: ConversationOutreachRequest,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> ConversationOutreachResult:
    """Новая вакансия из HR-first контакта: job в воронке + тред + опциональный скоринг.

    Первый HR-текст (initial_text) фоном триггерит извлечение события/предложение статуса
    воронки — тот же хвост, что уже стоит на /messages и /import.
    """
    try:
        result = await create_outreach(**body.model_dump(), account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    conv = conversation_out(result.conversation)
    if conv.thread is None:
        raise HTTPException(status_code=503, detail=NO_STORE)
    if body.initial_text.strip():
        background.add_task(
            on_incoming_hr_message, result.vacancy_id, "outreach", account_id=account.account_id
        )
    return ConversationOutreachResult(
        vacancy_id=result.vacancy_id, thread=conv.thread, scored=result.scored, conversation=conv
    )


@router.get("", response_model=ConversationList)
async def conversations_list(
    include_archived: bool = False,
    account: AccountContext = Depends(require_account_context),
) -> ConversationList:
    """Все разговоры (свежие сверху) для списка-хаба. Нет PG → пустой список, не валим вкладку."""
    try:
        from core.domains.pipeline.hr_threads import list_recent_threads

        threads = await list_recent_threads(
            include_archived=include_archived, account_id=account.account_id
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой список
        logger.debug("conversations: список недоступен (нет PG?): %s", exc)
        return ConversationList(items=[])
    return conversation_list(threads)


@router.get("/active-count")
async def conversations_active_count(
    account: AccountContext = Depends(require_account_context),
) -> dict[str, int]:
    """Число активных разговоров (без архива) для бейджа в сайдбаре. Нет PG → 0."""
    try:
        from core.domains.pipeline.hr_threads import count_active_threads

        return {"count": await count_active_threads(account_id=account.account_id)}
    except Exception as exc:  # noqa: BLE001 — нет PG → 0, сайдбар не падает
        logger.debug("conversations active-count недоступен (нет PG?): %s", exc)
        return {"count": 0}


@router.get("/attention", response_model=TodayAttention)
async def conversations_attention(
    account: AccountContext = Depends(require_account_context),
) -> TodayAttention:
    """Витрина дня «Чатов»: ответить / напомнить / скоро собес / свежие сильные.

    Роут объявлен ДО `/{vacancy_id}` — иначе FastAPI принял бы "attention" за vacancy_id.
    """
    return attention_out(await load_attention(account_id=account.account_id))


@router.get("/{vacancy_id}", response_model=ConversationOut)
async def conversation_get(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> ConversationOut:
    """Разговор по вакансии: тред + лента реплик. Нет PG/разговора → пустой (thread=None)."""
    return conversation_out(await load_conversation(vacancy_id, account_id=account.account_id))


@router.post("/{vacancy_id}/open", response_model=ConversationOut)
async def conversation_open(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> ConversationOut:
    """Явно открыть разговор известной вакансии (FR2-87: привязка без дампа) — гарантирует
    строку в `hr_threads`, даже без единой реплики, чтобы диалог не пропадал из списка слева."""
    try:
        view = await open_conversation(vacancy_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return conversation_out(view)


@router.post("/{vacancy_id}/messages", response_model=ConversationOut)
async def conversation_add_message(
    vacancy_id: str,
    body: ConversationMessageIn,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> ConversationOut:
    """Добавить реплику в разговор вакансии. 503 — нет PG.

    Входящее HR-сообщение (kind=hr_in) фоном триггерит пересчёт скора по фактам рекрутера.
    """
    try:
        view = await add_conversation_message(
            vacancy_id,
            kind=body.kind,
            body=body.body,
            sent_at=body.sent_at,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    if body.kind == "hr_in":
        background.add_task(
            on_incoming_hr_message, vacancy_id, "hr_message", account_id=account.account_id
        )
    return conversation_out(view)


@router.delete("/{vacancy_id}/messages/{message_id}", response_model=ConversationOut)
async def conversation_delete_message(
    vacancy_id: str,
    message_id: int,
    account: AccountContext = Depends(require_account_context),
) -> ConversationOut:
    """Удалить одну реплику ленты (выделение → Копировать/Удалить во фронте). 404 — не найдена."""
    try:
        view = await delete_conversation_message(
            vacancy_id, message_id, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return conversation_out(view)


@router.post("/{vacancy_id}/import", response_model=ConversationImportResult)
async def conversation_import(
    vacancy_id: str,
    body: ConversationImportRequest,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> ConversationImportResult:
    """Разобрать вставленный дамп переписки (LLM-сплиттер) → реплики hr_in/hr_out пачкой."""
    kwargs = {"attachment_ids": body.attachment_ids, "attachment_routes": body.attachment_routes}
    try:
        result = await import_correspondence(
            vacancy_id, body.text, **kwargs, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    conv = conversation_out(result.conversation)
    if "hr_in" in result.added_kinds:
        background.add_task(
            on_incoming_hr_message, vacancy_id, "hr_import", account_id=account.account_id
        )
    extra = {
        "added": result.added,
        "unrecognized_attachment_ids": result.unrecognized_attachment_ids,
    }
    return ConversationImportResult(**conv.model_dump(), **extra)


@router.post("/{vacancy_id}/vacancy-text", response_model=ConversationVacancyTextResult)
async def conversation_attach_vacancy_text(
    vacancy_id: str,
    body: ConversationVacancyTextRequest,
    account: AccountContext = Depends(require_account_context),
) -> ConversationVacancyTextResult:
    """Прикрепить полный текст вакансии, вставленный вручную (сайт без автопарсинга — не hh/gm)."""
    try:
        scored_job = await attach_vacancy_text_and_rescore(
            vacancy_id, body.text, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return ConversationVacancyTextResult(
        vacancy_id=vacancy_id, scored=True, overall_score=scored_job.score.overall_score
    )


@router.post("/{vacancy_id}/identity", response_model=ConversationIdentityResult)
async def conversation_update_identity(
    vacancy_id: str,
    body: ConversationIdentityRequest,
    account: AccountContext = Depends(require_account_context),
) -> ConversationIdentityResult:
    """Карандаш в шапке «Чатов»: поправить компанию/должность (executive-recruiter кейс — роль
    ещё не названа на момент первого контакта). Пересчитывает скор, если уже есть текст."""
    try:
        result = await update_vacancy_identity_and_rescore(
            vacancy_id, company=body.company, title=body.title, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return conversation_identity_out(vacancy_id, result)


@router.post("/{vacancy_id}/funnel-suggestion/apply", response_model=FunnelSuggestionApplyResult)
async def conversation_apply_funnel_suggestion(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> FunnelSuggestionApplyResult:
    """Один клик по чипу «Перевести в …?» — применить предложенный статус воронки."""
    from core.domains.pipeline.funnel_suggest import apply_funnel_suggestion

    try:
        status = await apply_funnel_suggestion(vacancy_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=NO_STORE) from exc
    return FunnelSuggestionApplyResult(
        vacancy_id=vacancy_id, status=status, applied=status is not None
    )


@router.post(
    "/{vacancy_id}/funnel-suggestion/dismiss", response_model=FunnelSuggestionDismissResult
)
async def conversation_dismiss_funnel_suggestion(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> FunnelSuggestionDismissResult:
    """Снять чип без смены воронки."""
    from core.domains.pipeline.funnel_suggest import dismiss_funnel_suggestion

    try:
        dismissed = await dismiss_funnel_suggestion(vacancy_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=NO_STORE) from exc
    return FunnelSuggestionDismissResult(vacancy_id=vacancy_id, dismissed=dismissed)


@router.patch("/by-thread/{thread_id}", response_model=HrThreadOut)
async def conversation_update(
    thread_id: int,
    body: HrThreadUpdate,
    account: AccountContext = Depends(require_account_context),
) -> HrThreadOut:
    """Правка разговора (статус: active/waiting/closed/archived; контакт; канал). 404/503."""
    try:
        updated = await update_conversation(
            thread_id, **body.model_dump(), account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return thread_out(updated)


@router.delete("/by-thread/{thread_id}", status_code=204, response_model=None)
async def conversation_delete(
    thread_id: int, account: AccountContext = Depends(require_account_context)
) -> None:
    """Удалить разговор (каскадом — его реплики). 503 — нет PG."""
    from core.domains.pipeline.hr_threads import delete_thread

    try:
        await delete_thread(thread_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=NO_STORE) from exc
