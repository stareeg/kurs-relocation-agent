"""Вкладка «Подготовка»: прицельная подготовка к этапу собеса по вакансии.

Сценарии домена — `core.domains.preparation.scenarios`; чат подготовки кросс-доменный
(preparation + assistant) — `core.app.scenarios.prep_chat`. Роутер — валидация, вызов,
маппинг ошибки / проекция.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from api.errors import to_http
from api.routers.assistant.mappers import prep_chat_history
from api.routers.preparation.mappers import (
    prep_chat_llm_history,
    prep_chat_response,
    prep_result,
    prep_sse_payloads,
    sobes_context_response,
    topics_response,
    vacancy_ref,
)
from api.schemas import (
    PrepChatHistory,
    PrepChatRequest,
    PrepChatResponse,
    PrepExportContextResponse,
    PrepGenerateRequest,
    PrepPackRegenerateResponse,
    PrepPackRequest,
    PrepPackSaveRequest,
    PrepParseExternalRequest,
    PrepResult,
    PrepSobesContextRequest,
    PrepSobesContextResponse,
    PrepTopicExpandRequest,
    PrepTopicExpandResponse,
    PrepTopicsGenerateRequest,
    PrepTopicsResponse,
    PrepTopicsReviewRequest,
)
from api.security import AccountContext, require_account_context
from api.streaming import sse_response, wants_sse
from core.app.scenarios import prep_chat as prep_chat_scenario
from core.domains.preparation import scenarios as prep
from core.domains.preparation.models import PrepStage
from core.domains.preparation.prep_pack import PrepPackDocument, get_prep_pack, save_prep_pack
from core.kernel.errors import DomainError

router = APIRouter(prefix="/api/prep", tags=["prep"])


@router.get("/{vacancy_id}", response_model=PrepResult)
async def get_prep(
    vacancy_id: str,
    stage: PrepStage = Query("screening"),
    company: str | None = Query(default=None, description="Название компании для профиля этапа"),
    account: AccountContext = Depends(require_account_context),
) -> PrepResult:
    """Последняя сохранённая подготовка. Нет PG/сессии → статический чеклист."""
    view = await prep.load_prep(vacancy_id, stage, company, account_id=account.account_id)
    return prep_result(view)


def _prep_sse_stream(
    vacancy_id: str, body: PrepGenerateRequest, *, account_id: int
) -> StreamingResponse:
    return sse_response(
        prep_sse_payloads(
            prep.generate_prep_events(
                vacancy_ref(vacancy_id, body),
                body.stage,
                focus_topics=body.focus_topics,
                account_id=account_id,
            )
        )
    )


@router.post("/{vacancy_id}/generate", response_model=PrepResult)
async def generate_prep(
    vacancy_id: str,
    body: PrepGenerateRequest,
    request: Request,
    account: AccountContext = Depends(require_account_context),
) -> PrepResult | StreamingResponse:
    """Сгенерировать подготовку под этап (LLM) и best-effort сохранить сессию в PG.
    `Accept: text/event-stream` → поток событий."""
    if wants_sse(request.headers.get("accept")):
        return _prep_sse_stream(vacancy_id, body, account_id=account.account_id)
    try:
        view = await prep.generate_prep(
            vacancy_ref(vacancy_id, body),
            body.stage,
            focus_topics=body.focus_topics,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return prep_result(view)


@router.get("/{vacancy_id}/chat", response_model=PrepChatHistory)
async def get_prep_chat(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> PrepChatHistory:
    """История чата подготовки по вакансии (хронологически). Нет PG → пустой список."""
    messages = await prep_chat_scenario.load_history(vacancy_id, account_id=account.account_id)
    attachments = await prep_chat_scenario.load_message_attachments(
        messages, account_id=account.account_id
    )
    return prep_chat_history(vacancy_id, messages, attachments)


@router.post("/{vacancy_id}/chat", response_model=PrepChatResponse)
async def post_prep_chat(
    vacancy_id: str,
    body: PrepChatRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepChatResponse:
    """Сообщение в чат подготовки: LLM + контекст вакансии; обе реплики пишутся в PG."""
    history = prep_chat_llm_history(body.history)
    try:
        reply = await prep_chat_scenario.send_message(
            vacancy_ref(vacancy_id, body),
            stage=body.stage,
            message=body.message,
            history=history,
            account_id=account.account_id,
            focus_topics=body.focus_topics,
            reply_to_message_id=body.reply_to_message_id,
            attachment_ids=body.attachment_ids,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return prep_chat_response(reply)


@router.delete("/{vacancy_id}/chat/{message_id}", response_model=PrepChatHistory)
async def delete_prep_chat_message_endpoint(
    vacancy_id: str,
    message_id: int,
    account: AccountContext = Depends(require_account_context),
) -> PrepChatHistory:
    """Удалить одну реплику чата подготовки (выделение → Удалить во фронте). 404 — не найдена."""
    try:
        history = await prep_chat_scenario.delete_message(
            vacancy_id, message_id, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    attachments = await prep_chat_scenario.load_message_attachments(
        history, account_id=account.account_id
    )
    return prep_chat_history(vacancy_id, history, attachments)


@router.delete("/{vacancy_id}/chat")
async def clear_prep_chat(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> dict[str, int]:
    """Очистить чат подготовки по вакансии. Возвращает число удалённых строк."""
    removed = await prep_chat_scenario.clear_chat(vacancy_id, account_id=account.account_id)
    return {"removed": removed}


@router.delete("/{vacancy_id}/questions")
async def clear_prep_questions_endpoint(
    vacancy_id: str,
    stage: PrepStage = Query("screening"),
    account: AccountContext = Depends(require_account_context),
) -> dict[str, bool]:
    """Обнулить пачки вопросов подготовки под этап (чат не трогает)."""
    try:
        from core.domains.preparation.prep import clear_prep_questions as _clear_q

        return {"cleared": await _clear_q(vacancy_id, stage, account_id=account.account_id)}
    except Exception:  # noqa: BLE001 — нет PG → нечего чистить
        return {"cleared": False}


@router.get("/{vacancy_id}/topics", response_model=PrepTopicsResponse)
async def get_prep_topics(
    vacancy_id: str,
    stage: PrepStage = Query("tech"),
    account: AccountContext = Depends(require_account_context),
) -> PrepTopicsResponse:
    """Готовность по темам под вакансию+этап. Пусто — ещё не генерили."""
    rows = await prep.load_topics(vacancy_id, stage, account_id=account.account_id)
    return topics_response(vacancy_id, stage, rows)


@router.post("/{vacancy_id}/topics/generate", response_model=PrepTopicsResponse)
async def generate_prep_topics_endpoint(
    vacancy_id: str,
    body: PrepTopicsGenerateRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepTopicsResponse:
    """Сгенерировать темы по вакансии (LLM). Без force не перетирает уже сохранённый набор."""
    try:
        rows = await prep.generate_topics(
            vacancy_ref(vacancy_id, body),
            body.stage,
            force=body.force,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return topics_response(vacancy_id, body.stage, rows)


@router.post("/{vacancy_id}/topics/review", response_model=PrepTopicsResponse)
async def review_prep_topics_endpoint(
    vacancy_id: str,
    body: PrepTopicsReviewRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepTopicsResponse:
    """Засчитать раскрытие ответа: явные темы или LLM-маппинг вопроса на каталог."""
    try:
        rows = await prep.review_topics(
            vacancy_id,
            body.stage,
            account_id=account.account_id,
            topics=list(body.topics),
            question_text=body.question_text or "",
            question_topic_hint=body.question_topic_hint,
            answer_excerpt=body.answer_excerpt,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return topics_response(vacancy_id, body.stage, rows)


@router.post("/{vacancy_id}/topics/expand", response_model=PrepTopicExpandResponse)
async def expand_prep_topic_endpoint(
    vacancy_id: str,
    body: PrepTopicExpandRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepTopicExpandResponse:
    """П.5c: раскрыть тему из разбора реального собеса (basic-tier LLM).

    Короткая markdown-шпаргалка: что входит в тему, типовые вопросы, что почитать.
    Stateles, кэшируется через общий llm_result_cache по теме+вакансии.
    """
    try:
        markdown = await prep.expand_topic(
            vacancy_ref(vacancy_id, body),
            body.stage,
            body.topic,
            account_id=account.account_id,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return PrepTopicExpandResponse(topic=body.topic, markdown=markdown)


@router.post("/{vacancy_id}/parse-external", response_model=PrepChatResponse)
async def parse_external_prep_endpoint(
    vacancy_id: str,
    body: PrepParseExternalRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepChatResponse:
    """Распарсить внешнюю переписку → вопросы в prep_sessions + короткая реплика в чат.

    Веб-UI сюда больше не ходит: режим композера «Внешний ИИ» убран, вставленную переписку
    разбирает сам чат подготовки (`answer_prep_chat` сам решает, продолжение это разговора или
    сторонние готовые пары вопрос-ответ). Эндпоинт остаётся для программных клиентов и как
    явный «только распарсить, без диалога» путь.
    """
    try:
        reply = await prep_chat_scenario.parse_external(
            vacancy_ref(vacancy_id, body),
            stage=body.stage,
            transcript=body.transcript,
            account_id=account.account_id,
            attachment_ids=body.attachment_ids,
            attachment_routes=body.attachment_routes,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return prep_chat_response(reply)


@router.post("/{vacancy_id}/sobes-context", response_model=PrepSobesContextResponse)
async def generate_sobes_context(
    vacancy_id: str,
    body: PrepSobesContextRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepSobesContextResponse:
    """Компактный контекст для оверлея sobes.tech под выбранный формат этапа."""
    try:
        overlay = await prep.build_sobes_overlay(
            vacancy_ref(vacancy_id, body),
            body.stage,
            account_id=account.account_id,
            force=body.force,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return sobes_context_response(overlay)


@router.get("/{vacancy_id}/export-context", response_model=PrepExportContextResponse)
async def get_export_context(
    vacancy_id: str,
    stage: PrepStage | None = Query(default=None),
    account: AccountContext = Depends(require_account_context),
) -> PrepExportContextResponse:
    """Вакансия+оффер+HR+расшифровки+вопросы этапа — одним текстом для внешнего LLM."""
    from core.domains.preparation.interview.export_context import build_full_export

    try:
        text = await build_full_export(vacancy_id, stage=stage, account_id=account.account_id)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PrepExportContextResponse(text=text)


@router.get("/{vacancy_id}/pack", response_model=PrepPackDocument)
async def get_prep_pack_endpoint(
    vacancy_id: str,
    stage: PrepStage = Query("tech"),
    account: AccountContext = Depends(require_account_context),
) -> PrepPackDocument:
    """Прочитать сохранённый бриф под (vacancy, stage). Нет PG/брифа → пустой бриф."""
    return await get_prep_pack(vacancy_id, stage, account_id=account.account_id)


@router.post("/{vacancy_id}/pack/regenerate", response_model=PrepPackRegenerateResponse)
async def regenerate_prep_pack_endpoint(
    vacancy_id: str,
    body: PrepPackRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepPackRegenerateResponse:
    """Собрать свежий бриф (LLM, если вход изменился). Ничего не сохраняет — кандидат для ревью."""
    try:
        ref = vacancy_ref(vacancy_id, body)
        text, input_hash = await prep.regenerate_prep_pack(
            ref, body.stage, account_id=account.account_id
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    return PrepPackRegenerateResponse(text=text, input_hash=input_hash)


@router.put("/{vacancy_id}/pack", response_model=PrepPackDocument)
async def put_prep_pack_endpoint(
    vacancy_id: str,
    body: PrepPackSaveRequest,
    account: AccountContext = Depends(require_account_context),
) -> PrepPackDocument:
    """Сохранить принятый бриф (upsert). Нет PG → 503."""
    try:
        return await save_prep_pack(
            vacancy_id,
            body.stage,
            body.content,
            input_hash=body.input_hash,
            account_id=account.account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → нельзя сохранить
        from core.kernel.errors import StorageUnavailable

        raise to_http(StorageUnavailable("Postgres недоступен")) from exc
