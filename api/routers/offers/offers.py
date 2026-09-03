"""Офферы — путь веба под `/api/offers` (парсинг письма HR → сравнение → решение).

Старый контур `/vacancies/{id}/offer*` и корневой `/offers/decide` удалён — веб давно
на `/api/offers/*`, у старых путей не осталось потребителей (extension/bot их не звали).
`offer_parse`/`_offers_decide` остались внутренними хелперами под `/api/offers/*`-алиасами.

Персистентность — Postgres (`core.domains.offers.store`, источник истины); кросс-доменные
сценарии (парсинг с подсказками из `jobs`, сравнение, торг с бенчмарком рынка) —
`core.app.scenarios.offers`.

M2 (plans/multitenancy_gaps_2026_08_06.md §3.2): весь роутер — за
`require_account_context` (`account_id` из токена запроса) — раньше `GET /api/offers` отдавал
офферы всех аккаунтов системы (S1).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.errors import to_http
from api.schemas.offers import OffersChatHistory
from api.security import AccountContext, require_account_context
from api.streaming import sse_response, wants_sse
from core.app.scenarios.offers import (
    NOT_FOUND,
    ComparisonResult,
    compare,
    compare_events,
    feed_offer_corpus,
    load_offers_chat_view,
    negotiate,
    parse_and_store,
    recompute_bonus_estimate,
    to_record,
)
from core.domains.offers.bonus import apply_bonus_patch
from core.domains.offers.models import (
    OfferCompareRequest,
    OfferCompareResponse,
    OfferCreateRequest,
    OfferNegotiateResponse,
    OfferParseApiRequest,
    OfferParseRequest,
    OfferRecord,
    OfferReorderRequest,
    OfferUpdateRequest,
)
from core.domains.offers.store import (
    Offer,
    delete_offer,
    load_all_offers,
    load_offer,
    reorder_offers,
    upsert_offer,
)
from core.kernel.errors import DomainError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["offers"])


async def _patch_offer(
    vacancy_id: str, body: OfferUpdateRequest, background: BackgroundTasks, *, account_id: int
):
    """Общее тело правки оффера: 404 без оффера, пустой патч — no-op, иначе перезапись полей."""
    existing = await load_offer(vacancy_id, account_id=account_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    updates = apply_bonus_patch(body.model_dump(exclude_unset=True))
    if not updates:
        return to_record(existing)
    saved = await upsert_offer(
        existing.model_copy(update=updates), account_id=account_id, merge=False
    )
    background.add_task(feed_offer_corpus, vacancy_id, account_id=account_id)
    # % годовой/квартальной — сразу в ответе, иначе шапка «₽/год» ещё без премии
    # (или со старым equiv). KPI/LLM — фоном, как раньше.
    recomputed = await recompute_bonus_estimate(vacancy_id, account_id=account_id, allow_llm=False)
    if recomputed is not None:
        saved = recomputed
    background.add_task(recompute_bonus_estimate, vacancy_id, account_id=account_id)
    return to_record(saved)


async def _offer_parse(
    vacancy_id: str, body: OfferParseRequest, background: BackgroundTasks, *, account_id: int
) -> OfferRecord:
    """Извлечь структуру оффера из текста письма HR и сохранить (merge или overwrite)."""
    try:
        record = await parse_and_store(
            vacancy_id, body.text, account_id=account_id, overwrite=body.overwrite
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    background.add_task(feed_offer_corpus, vacancy_id, account_id=account_id)
    return record


async def _offers_decide_sse_events(
    body: OfferCompareRequest, *, account_id: int
) -> AsyncIterator[dict[str, Any]]:
    """Доменные события сравнения → payload'ы единого SSE."""
    async for event in compare_events(
        account_id=account_id, vacancy_ids=body.vacancy_ids or None, max_age_days=body.max_age_days
    ):
        if event.get("type") == "done":
            result = event["result"]
            assert isinstance(result, ComparisonResult)
            response = OfferCompareResponse(**result.model_dump())
            yield {"type": "done", "response": response.model_dump(mode="json")}
        else:
            yield event


async def _offers_decide(
    body: OfferCompareRequest, request: Request, *, account_id: int
) -> OfferCompareResponse | StreamingResponse:
    """Сравнить активные офферы под приоритеты кандидата (LLM, с кэшом по слепку набора).
    `Accept: text/event-stream` → поток событий (`save_to_disk` в потоке не поддержан)."""
    if wants_sse(request.headers.get("accept")):
        return sse_response(_offers_decide_sse_events(body, account_id=account_id))
    try:
        result = await compare(account_id=account_id, **body.model_dump())
    except DomainError as exc:
        raise to_http(exc) from exc
    return OfferCompareResponse(**result.model_dump())


# ---------------------------------------------------------------------------
# Фронтовые эндпоинты матрицы сравнения под /api/offers. PG не жёсткая зависимость:
# нет пула → список деградирует в [], вкладка не падает.
# ---------------------------------------------------------------------------


@router.get("/api/offers", response_model=list[OfferRecord])
async def offers_list(
    account: AccountContext = Depends(require_account_context),
) -> list[OfferRecord]:
    """Все офферы аккаунта для матрицы сравнения (свежие первыми). Нет PG → пустой список."""
    try:
        offers = await load_all_offers(limit=100, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая матрица, не валим вкладку
        logger.debug("Offers list: Postgres недоступен: %s", exc)
        return []
    return [to_record(o) for o in offers]


@router.get("/api/offers/chat", response_model=OffersChatHistory)
async def get_offers_chat(
    account: AccountContext = Depends(require_account_context),
) -> OffersChatHistory:
    """История чата вкладки «Офферы» (хронологически). Нет PG → пустой список.

    Статический путь зарегистрирован до `/api/offers/{vacancy_id}`, иначе DELETE chat
    перехватился бы как удаление оффера с vacancy_id='chat'.
    """
    from api.routers.offers.mappers import offers_chat_history

    messages, attachments = await load_offers_chat_view(account_id=account.account_id)
    return offers_chat_history(messages, attachments)


@router.delete("/api/offers/chat")
async def clear_offers_chat_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> dict[str, int]:
    """Очистить чат вкладки «Офферы». Возвращает число удалённых строк."""
    from core.domains.offers.offers_chat import clear_offers_chat

    removed = await clear_offers_chat(account_id=account.account_id)
    return {"removed": removed}


@router.delete("/api/offers/chat/messages/{message_id}")
async def delete_offers_chat_message_endpoint(
    message_id: int,
    account: AccountContext = Depends(require_account_context),
) -> dict[str, bool]:
    """Удалить одну реплику (выделение → Удалить)."""
    from core.domains.offers.offers_chat import delete_offers_chat_messages

    removed = await delete_offers_chat_messages([message_id], account_id=account.account_id)
    return {"deleted": removed > 0}


@router.post("/api/offers", response_model=OfferRecord)
async def offers_create(
    body: OfferCreateRequest, account: AccountContext = Depends(require_account_context)
) -> OfferRecord:
    """Создать колонку оффера под вакансию (если ещё нет). Поля правятся инлайн через PATCH."""
    existing = await load_offer(body.vacancy_id, account_id=account.account_id)
    if existing is not None:
        return to_record(existing)
    saved = await upsert_offer(
        Offer(vacancy_id=body.vacancy_id, company=body.company, position=body.position),
        account_id=account.account_id,
        merge=False,
    )
    return to_record(saved)


@router.patch("/api/offers/{vacancy_id}", response_model=OfferRecord)
async def offers_patch(
    vacancy_id: str,
    body: OfferUpdateRequest,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> OfferRecord:
    """Инлайн-правка ячейки матрицы (перезапись заданных полей). 404 — оффера нет."""
    return await _patch_offer(vacancy_id, body, background, account_id=account.account_id)


@router.delete("/api/offers/{vacancy_id}", status_code=204, response_model=None)
async def offers_delete(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> None:
    """Убрать колонку оффера из матрицы."""
    await delete_offer(vacancy_id, account_id=account.account_id)


@router.post("/api/offers/reorder", response_model=list[OfferRecord])
async def offers_reorder(
    body: OfferReorderRequest, account: AccountContext = Depends(require_account_context)
) -> list[OfferRecord]:
    """Ручной порядок колонок матрицы (drag-n-drop): индекс в списке = приоритет."""
    offers = await reorder_offers(body.vacancy_ids, account_id=account.account_id)
    return [to_record(o) for o in offers]


@router.post("/api/offers/decide", response_model=OfferCompareResponse)
async def offers_decide_api(
    body: OfferCompareRequest,
    request: Request,
    account: AccountContext = Depends(require_account_context),
) -> OfferCompareResponse | StreamingResponse:
    """Фронтовый алиас сравнения офферов (vite проксирует только /api)."""
    return await _offers_decide(body, request, account_id=account.account_id)


@router.post("/api/offers/{vacancy_id}/negotiate", response_model=OfferNegotiateResponse)
async def offers_negotiate(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> OfferNegotiateResponse:
    """Аргументы для торга по офферу (бенчмарк + другие офферы + leverage воронки).

    Персистится на офере — перечитывается при заходе на вкладку, кнопка «Торг» регенерирует явно.
    """
    try:
        result = await negotiate(vacancy_id, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return OfferNegotiateResponse(offer=result.offer, negotiation=result.negotiation)


@router.post("/api/offers/parse", response_model=OfferRecord)
async def offers_parse_api(
    body: OfferParseApiRequest,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> OfferRecord:
    """Фронтовый алиас парсинга письма HR под оффер: `vacancy_id` в теле, а не в пути."""
    parse_request = OfferParseRequest(text=body.text, overwrite=body.overwrite)
    return await _offer_parse(
        body.vacancy_id, parse_request, background, account_id=account.account_id
    )
