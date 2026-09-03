"""Вкладка «Заметки» / контексты для чата: markdown-шпаргалки с полнотекстовым поиском.

Персистентность — Postgres (`core.domains.assistant.notes`). Список деградирует в пустой при недоступном PG
(как `resume_stats` — лёгкая вкладка, не должна ронять фронт); CRUD-мутации ошибку PG не глотают —
запись должна либо реально сохраниться, либо владелец увидит ошибку, а не молчаливую потерю текста.

Контекст — текст в `notes.body` (+ `use_in_rag`), не LLM-чат. Диалоги с моделью — только
в чатах по вакансиям (`/api/conversations` и т.п.).

M4 (plans/multitenancy_gaps_2026_08_06.md §3.4): весь роутер — за `require_account_context`
— раньше `GET /api/notes` отдавал заметки всех аккаунтов системы (S1).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.schemas import (
    NoteCreateRequest,
    NoteMessageCreateRequest,
    NoteMessageUpdateRequest,
    NoteUpdateRequest,
)
from api.security import AccountContext, require_account_context
from core.domains.assistant.notes import (
    Note,
    NoteMessage,
    add_note_message,
    create_note,
    delete_note,
    delete_note_message,
    list_note_messages,
    list_notes,
    search_notes,
    update_note,
    update_note_message,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=list[Note])
async def get_notes(
    q: str = "", account: AccountContext = Depends(require_account_context)
) -> list[Note]:
    """Список заметок; `q` — полнотекстовый поиск (пусто — все заметки). Нет PG → пустой список."""
    try:
        return (
            await search_notes(q, account_id=account.account_id)
            if q.strip()
            else await list_notes(account_id=account.account_id)
        )
    except Exception as exc:  # noqa: BLE001 — нет PG → вкладка пустая, не падает
        logger.debug("notes: список недоступен (нет PG?): %s", exc)
        return []


@router.post("", response_model=Note)
async def post_note(
    body: NoteCreateRequest, account: AccountContext = Depends(require_account_context)
) -> Note:
    """Создать заметку."""
    return await create_note(
        body.title,
        body.body,
        body.tags,
        use_in_rag=body.use_in_rag,
        account_id=account.account_id,
    )


@router.patch("/{note_id}", response_model=Note)
async def patch_note(
    note_id: int,
    body: NoteUpdateRequest,
    account: AccountContext = Depends(require_account_context),
) -> Note:
    """Правка заметки по id (None-поля не трогаются)."""
    updated = await update_note(
        note_id,
        title=body.title,
        body=body.body,
        tags=body.tags,
        use_in_rag=body.use_in_rag,
        account_id=account.account_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="заметка не найдена")
    return updated


@router.delete("/{note_id}", status_code=204, response_model=None)
async def delete_note_endpoint(
    note_id: int, account: AccountContext = Depends(require_account_context)
) -> None:
    """Удалить заметку. Нет заметки — тоже 204 (идемпотентно, как остальные delete в API)."""
    await delete_note(note_id, account_id=account.account_id)


# --- Сообщения контекста (UX7): контекст выглядит как чат, реплики только владельца ---


@router.get("/{note_id}/messages", response_model=list[NoteMessage])
async def get_note_messages(
    note_id: int, account: AccountContext = Depends(require_account_context)
) -> list[NoteMessage]:
    """Лента сообщений контекста. Нет PG → пустой список (вкладка не падает)."""
    try:
        return await list_note_messages(note_id, account_id=account.account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → пусто, не 500
        logger.debug("notes: сообщения контекста недоступны (нет PG?): %s", exc)
        return []


@router.post("/{note_id}/messages", response_model=NoteMessage)
async def post_note_message(
    note_id: int,
    body: NoteMessageCreateRequest,
    account: AccountContext = Depends(require_account_context),
) -> NoteMessage:
    """Добавить сообщение в контекст (композер внизу ленты). Заметка не найдена/чужая → 404."""
    created = await add_note_message(note_id, body.body, account_id=account.account_id)
    if created is None:
        raise HTTPException(status_code=404, detail="заметка не найдена")
    return created


@router.patch("/{note_id}/messages/{message_id}", response_model=NoteMessage)
async def patch_note_message(
    note_id: int,
    message_id: int,
    body: NoteMessageUpdateRequest,
    account: AccountContext = Depends(require_account_context),
) -> NoteMessage:
    """Правка сообщения контекста (клик по сообщению → редактирование)."""
    updated = await update_note_message(
        note_id, message_id, body.body, account_id=account.account_id
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="сообщение не найдено")
    return updated


@router.delete("/{note_id}/messages/{message_id}", status_code=204, response_model=None)
async def delete_note_message_endpoint(
    note_id: int,
    message_id: int,
    account: AccountContext = Depends(require_account_context),
) -> None:
    """Удалить одно сообщение контекста. Нет строки — тоже 204 (идемпотентно)."""
    await delete_note_message(note_id, message_id, account_id=account.account_id)
