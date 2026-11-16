"""Repository серверного персиста главного чата агента (A-3).

Диалоги «Агента» живут на сервере: сессии (список слева) и реплики. Раньше история
держалась только в localStorage вкладки — она не переживала другой браузер и не
связывалась с запусками агента (`agent_runs.session_id`).

Простое подмножество разговоров вакансий (`hr_threads`): без воронки и типов реплик —
только user/assistant, порядок по id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import Executor, row_to_dict

logger = logging.getLogger(__name__)

_TITLE_FROM_MESSAGE_MAX = 60


@dataclass(frozen=True, slots=True)
class AgentChatSession:
    """Строка `agent_chat_sessions`: один диалог главного чата."""

    id: int
    title: str
    created_at: Any = None
    updated_at: Any = None


@dataclass(frozen=True, slots=True)
class AgentChatMessage:
    """Реплика диалога: роль user/assistant и текст."""

    id: int
    session_id: int
    role: str
    content: str
    created_at: Any = None


def _session_from_row(row: Any) -> AgentChatSession | None:
    if row is None:
        return None
    data = row_to_dict(row)
    return AgentChatSession(
        id=int(data["id"]),
        title=str(data["title"]),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _message_from_row(row: Any) -> AgentChatMessage:
    data = row_to_dict(row)
    return AgentChatMessage(
        id=int(data["id"]),
        session_id=int(data["session_id"]),
        role=str(data["role"]),
        content=str(data["content"]),
        created_at=data.get("created_at"),
    )


async def create_session(
    *, account_id: int, title: str = "Новый диалог", db: Executor | None = None
) -> AgentChatSession:
    """Новый диалог. Заголовок по умолчанию — обновится первой репликой пользователя."""
    if db is not None:
        row = await db.fetchrow(
            "insert into agent_chat_sessions (account_id, title) values ($1, $2)"
            " returning id, title, created_at, updated_at",
            account_id,
            title,
        )
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(
                "insert into agent_chat_sessions (account_id, title) values ($1, $2)"
                " returning id, title, created_at, updated_at",
                account_id,
                title,
            )
    session = _session_from_row(row)
    assert session is not None  # insert … returning всегда даёт строку
    return session


async def list_sessions(*, account_id: int, limit: int = 50) -> list[AgentChatSession]:
    """Диалоги аккаунта, свежие сверху."""
    async with account_scope(account_id) as scoped:
        rows = await scoped.fetch(
            "select id, title, created_at, updated_at from agent_chat_sessions"
            " where account_id = $1 order by updated_at desc, id desc limit $2",
            account_id,
            limit,
        )
    return [s for s in (_session_from_row(row) for row in rows) if s is not None]


async def get_session(
    session_id: int, *, account_id: int, db: Executor | None = None
) -> AgentChatSession | None:
    """Диалог аккаунта или None (чужой/несуществующий — роутер отвечает 404)."""
    if db is not None:
        row = await db.fetchrow(
            "select id, title, created_at, updated_at from agent_chat_sessions"
            " where id = $1 and account_id = $2",
            session_id,
            account_id,
        )
    else:
        async with account_scope(account_id) as scoped:
            row = await scoped.fetchrow(
                "select id, title, created_at, updated_at from agent_chat_sessions"
                " where id = $1 and account_id = $2",
                session_id,
                account_id,
            )
    return _session_from_row(row)


async def rename_session(
    session_id: int, title: str, *, account_id: int
) -> AgentChatSession | None:
    """Переименовать диалог (заголовок в списке слева)."""
    async with account_scope(account_id) as scoped:
        row = await scoped.fetchrow(
            "update agent_chat_sessions set title = $3, updated_at = now()"
            " where id = $1 and account_id = $2 returning id, title, created_at, updated_at",
            session_id,
            account_id,
            title,
        )
    return _session_from_row(row)


async def delete_session(session_id: int, *, account_id: int) -> bool:
    """Удалить диалог (реплики и привязанные запуски-сессии каскадом; runs остаются без сессии).

    Запуски агента не удаляем: их журнал полезен и в админке (U-3), а `session_id` в
    `agent_runs` — необязательная ссылка (миграция 0155 без FK на сессию).
    """
    async with account_scope(account_id) as scoped:
        raw = await scoped.execute(
            "delete from agent_chat_sessions where id = $1 and account_id = $2",
            session_id,
            account_id,
        )
    return raw.endswith("1")


async def list_messages(
    session_id: int, *, account_id: int, limit: int = 500
) -> list[AgentChatMessage]:
    """Реплики диалога по порядку (последние `limit`)."""
    async with account_scope(account_id) as scoped:
        rows = await scoped.fetch(
            "select id, session_id, role, content, created_at from ("
            " select id, session_id, role, content, created_at from agent_chat_messages"
            " where session_id = $1 and account_id = $2 order by id desc limit $3"
            ") t order by id",
            session_id,
            account_id,
            limit,
        )
    return [_message_from_row(row) for row in rows]


async def append_message(
    *, session_id: int, account_id: int, role: str, content: str
) -> AgentChatMessage:
    """Добавить реплику и тронуть `updated_at` сессии; первая реплика задаёт заголовок.

    Одним statement'ом (CTE): вставка реплики + обновление сессии атомарно, и pyright
    не требует `transaction()` от Protocol-соединения.
    """
    async with account_scope(account_id) as scoped:
        row = await scoped.fetchrow(
            "with msg as ("
            " insert into agent_chat_messages (session_id, account_id, role, content)"
            " values ($1, $2, $3, $4)"
            " returning id, session_id, role, content, created_at"
            "), sess as ("
            " update agent_chat_sessions s"
            " set updated_at = now(),"
            "     title = case"
            "       when $3 = 'user' and s.title = 'Новый диалог'"
            "         then coalesce(nullif(left(btrim($4), $5), ''), s.title)"
            "       else s.title end"
            " where s.id = $1 and s.account_id = $2"
            " returning 1"
            ") select id, session_id, role, content, created_at from msg",
            session_id,
            account_id,
            role,
            content,
            _TITLE_FROM_MESSAGE_MAX,
        )
    message = _message_from_row(row)
    assert message is not None  # insert … returning всегда даёт строку
    return message


__all__ = [
    "AgentChatMessage",
    "AgentChatSession",
    "append_message",
    "create_session",
    "delete_session",
    "get_session",
    "list_messages",
    "list_sessions",
    "rename_session",
]
