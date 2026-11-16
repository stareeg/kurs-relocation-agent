"""Чат-сессии главного чата агента (A-3): серверные диалоги и реплики.

Список слева в «Агенте» берётся отсюда; раньше история жила только в localStorage
вкладки. Реплики пишет фронт (user — при отправке, assistant — после ответа стрима),
запуски агента привязываются к сессии через `agent_runs.session_id`.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from api.errors import to_http
from api.schemas import (
    AgentChatMessageIn,
    AgentChatMessageList,
    AgentChatMessageOut,
    AgentChatSessionCreate,
    AgentChatSessionList,
    AgentChatSessionOut,
    AgentChatSessionRename,
)
from api.security import AccountContext, require_account_context
from core.kernel.errors import DomainError
from core.platform.repo import agent_chats as chats_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent/chats", tags=["agent-chats"])


def session_out(record: Any) -> AgentChatSessionOut:
    """Строка сессии → контракт."""
    return AgentChatSessionOut(
        id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def message_out(record: Any) -> AgentChatMessageOut:
    """Строка реплики → контракт."""
    return AgentChatMessageOut(
        id=record.id,
        session_id=record.session_id,
        role=record.role,
        content=record.content,
        created_at=record.created_at,
    )


@router.post("", response_model=AgentChatSessionOut, status_code=201)
async def create_chat_session(
    body: AgentChatSessionCreate | None = None,
    account: AccountContext = Depends(require_account_context),
) -> AgentChatSessionOut:
    """Новый диалог. Заголовок уточнится первой репликой пользователя."""
    title = (body.title.strip() if body and body.title else None) or "Новый диалог"
    try:
        session = await chats_repo.create_session(account_id=account.account_id, title=title)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return session_out(session)


@router.get("", response_model=AgentChatSessionList)
async def list_chat_sessions(
    limit: int = 50, account: AccountContext = Depends(require_account_context)
) -> AgentChatSessionList:
    """Диалоги аккаунта, свежие сверху. Нет PG → пустой список, вкладка не падает."""
    try:
        sessions = await chats_repo.list_sessions(
            account_id=account.account_id, limit=min(limit, 100)
        )
    except RuntimeError as exc:
        logger.debug("agent chats: список недоступен (нет PG?): %s", exc)
        return AgentChatSessionList(items=[])
    return AgentChatSessionList(items=[session_out(s) for s in sessions])


@router.patch("/{session_id}", response_model=AgentChatSessionOut)
async def rename_chat_session(
    session_id: int,
    body: AgentChatSessionRename,
    account: AccountContext = Depends(require_account_context),
) -> AgentChatSessionOut:
    """Переименовать диалог. 404 — чужой/несуществующий; 503 — нет PG."""
    try:
        session = await chats_repo.rename_session(
            session_id, body.title.strip(), account_id=account.account_id
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    if session is None:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    return session_out(session)


@router.delete("/{session_id}", status_code=204, response_model=None)
async def delete_chat_session(
    session_id: int, account: AccountContext = Depends(require_account_context)
) -> None:
    """Удалить диалог с репликами (запуски остаются в журнале). 404/503."""
    try:
        deleted = await chats_repo.delete_session(session_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Диалог не найден")


@router.get("/{session_id}/messages", response_model=AgentChatMessageList)
async def list_chat_messages(
    session_id: int,
    limit: int = 500,
    account: AccountContext = Depends(require_account_context),
) -> AgentChatMessageList:
    """Реплики диалога по порядку. 404 — чужой/несуществующий."""
    try:
        session = await chats_repo.get_session(session_id, account_id=account.account_id)
        if session is None:
            raise DomainError("Диалог не найден", code="not_found")
        messages = await chats_repo.list_messages(
            session_id, account_id=account.account_id, limit=min(limit, 1000)
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return AgentChatMessageList(items=[message_out(m) for m in messages])


@router.post("/{session_id}/messages", response_model=AgentChatMessageOut, status_code=201)
async def append_chat_message(
    session_id: int,
    body: AgentChatMessageIn,
    account: AccountContext = Depends(require_account_context),
) -> AgentChatMessageOut:
    """Добавить реплику (user или assistant) и обновить сессию в списке."""
    try:
        session = await chats_repo.get_session(session_id, account_id=account.account_id)
        if session is None:
            raise DomainError("Диалог не найден", code="not_found")
        message = await chats_repo.append_message(
            session_id=session_id,
            account_id=account.account_id,
            role=body.role,
            content=body.content,
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return message_out(message)
