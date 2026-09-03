"""Вкладка «HR переписки»: хранилище диалогов с HR по вакансии.

Диалог с HR часто уходит из hh в Telegram (ссылка в разделе «Обо мне»). Ведём его в системе,
привязываем к вакансии, чтобы по десяткам параллельных процессов не теряться (CLAUDE.md). v1 —
ручной ввод (вставка из TG) + хранение + показ, без LLM.

Персистентность — Postgres (`core.domains.pipeline.hr_threads`, ленивый импорт внутри хендлеров — чистая
деградация + monkeypatch в тестах). PG не жёсткая для чтения: нет пула → списки деградируют в пустые
(не 500). Запись требует пул → 503.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.schemas import (
    HrDirectionClassifyRequest,
    HrDirectionClassifyResponse,
    HrMessageCreate,
    HrMessageList,
    HrMessageOut,
    HrThreadCreate,
    HrThreadList,
    HrThreadOut,
    HrThreadUpdate,
)
from api.security import AccountContext, require_account_context

if TYPE_CHECKING:
    from core.domains.pipeline.hr_threads import HrMessage, HrThread

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hr-threads", tags=["hr-threads"])

_NO_STORE = "Хранилище переписок недоступно"


def _thread_out(thread: HrThread) -> HrThreadOut:
    return HrThreadOut.model_validate(thread.model_dump())


def _message_out(message: HrMessage) -> HrMessageOut:
    return HrMessageOut.model_validate(message.model_dump())


@router.get("", response_model=HrThreadList)
async def threads_list(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> HrThreadList:
    """Треды по вакансии (свежие сверху). Нет PG → пустой список, не валим вкладку."""
    try:
        from core.domains.pipeline.hr_threads import list_threads_by_vacancy

        threads = await list_threads_by_vacancy(vacancy_id, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой список
        logger.debug("hr-threads: список недоступен (нет PG?): %s", exc)
        return HrThreadList(vacancy_id=vacancy_id, items=[])
    return HrThreadList(vacancy_id=vacancy_id, items=[_thread_out(t) for t in threads])


@router.post("", response_model=HrThreadOut)
async def thread_create(
    body: HrThreadCreate, account: AccountContext = Depends(require_account_context)
) -> HrThreadOut:
    """Завести тред под вакансию (контакт/канал). Требует PG → 503, если пул не поднят."""
    from core.domains.pipeline.hr_threads import HrThread, save_thread

    try:
        saved = await save_thread(
            HrThread(
                vacancy_id=body.vacancy_id,
                contact_name=body.contact_name,
                channel=body.channel,
                company=body.company,
            ),
            account_id=account.account_id,
        )
    except RuntimeError as exc:  # пул PG не поднят
        logger.warning("hr-threads: тред не создан (нет PG): %s", exc)
        raise HTTPException(status_code=503, detail=_NO_STORE) from exc
    logger.info("hr-threads: создан тред vacancy_id=%s channel=%s", body.vacancy_id, body.channel)
    return _thread_out(saved)


@router.post("/classify-direction", response_model=HrDirectionClassifyResponse)
async def classify_direction(
    body: HrDirectionClassifyRequest,
    account: AccountContext = Depends(require_account_context),
) -> HrDirectionClassifyResponse:
    """EXT-H1: LLM-фолбэк направления реплик, которые DOM-эвристика расширения не распознала.

    Без БД для самого треда — чистая классификация текста (тред приходит целиком, ещё до
    создания в hr_threads); резюме аккаунта запроса читается только ради identity в промпте
    (S-critical 2026-08-26 — раньше без account_id классификатор молча брал резюме владельца
    инсталляции). LLM недоступна/упала → пустой `resolved`, расширение падает на прежний
    fallback (без надёжного сигнала не угадываем), остальной синк это не роняет.
    """
    from core.domains.pipeline.hr_direction_llm import ThreadMessageIn, classify_hr_directions_llm

    messages = [
        ThreadMessageIn(
            index=m.index,
            kind=m.kind if m.kind in ("hr_in", "hr_out") else None,
            body=m.body,
        )
        for m in body.messages
    ]
    resolved = await classify_hr_directions_llm(messages, account_id=account.account_id)
    return HrDirectionClassifyResponse(
        resolved=cast(dict[int, Literal["hr_in", "hr_out"]], resolved)
    )


@router.patch("/{thread_id}", response_model=HrThreadOut)
async def thread_update(
    thread_id: int,
    body: HrThreadUpdate,
    account: AccountContext = Depends(require_account_context),
) -> HrThreadOut:
    """Правка треда (статус чипами / контакт / канал). 404 — треда нет, 503 — нет PG."""
    from core.domains.pipeline.hr_threads import update_thread

    try:
        updated = await update_thread(
            thread_id,
            status=body.status,
            contact_name=body.contact_name,
            channel=body.channel,
            company=body.company,
            account_id=account.account_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_NO_STORE) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Тред не найден")
    return _thread_out(updated)


@router.delete("/{thread_id}", status_code=204, response_model=None)
async def thread_delete(
    thread_id: int, account: AccountContext = Depends(require_account_context)
) -> None:
    """Удалить тред (каскадом — его сообщения). 503 — нет PG."""
    from core.domains.pipeline.hr_threads import delete_thread

    try:
        await delete_thread(thread_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_NO_STORE) from exc


@router.get("/{thread_id}/messages", response_model=HrMessageList)
async def messages_list(
    thread_id: int, account: AccountContext = Depends(require_account_context)
) -> HrMessageList:
    """Лента сообщений треда по времени. Нет PG → пустой список."""
    try:
        from core.domains.pipeline.hr_threads import list_messages

        messages = await list_messages(thread_id, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пустая лента
        logger.debug("hr-threads: лента недоступна (нет PG?): %s", exc)
        return HrMessageList(thread_id=thread_id, items=[])
    return HrMessageList(thread_id=thread_id, items=[_message_out(m) for m in messages])


@router.post("/{thread_id}/messages", response_model=HrMessageOut)
async def message_add(
    thread_id: int,
    body: HrMessageCreate,
    background: BackgroundTasks,
    account: AccountContext = Depends(require_account_context),
) -> HrMessageOut:
    """Добавить сообщение в тред (ручной ввод, вставка из TG). 404 — треда нет, 503 — нет PG.

    Полный авто: входящее сообщение от HR (direction=in) фоном триггерит пересчёт скора
    по фактам — рекрутер мог назвать вилку/формат/грейд. Best-effort, ввод не блокирует.
    """
    from core.domains.pipeline.hr_threads import HrMessage, add_message, get_thread

    try:
        thread = await get_thread(thread_id, account_id=account.account_id)
    except RuntimeError as exc:
        logger.warning("hr-threads: сообщение не добавлено (нет PG): %s", exc)
        raise HTTPException(status_code=503, detail=_NO_STORE) from exc
    if thread is None:
        raise HTTPException(status_code=404, detail="Тред не найден")
    try:
        saved = await add_message(
            HrMessage(
                thread_id=thread_id,
                direction=body.direction,
                body=body.body,
                sent_at=body.sent_at,
            ),
            account_id=account.account_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=_NO_STORE) from exc

    # Пересчёт только на входящих (слова HR); исходящие наши — нового факта не несут.
    if body.direction == "in" and thread.vacancy_id:
        from core.domains.opportunities.recalibrate import rescore_from_hr_facts_safe

        background.add_task(
            rescore_from_hr_facts_safe,
            thread.vacancy_id,
            trigger="hr_message",
            account_id=account.account_id,
        )
    return _message_out(saved)
