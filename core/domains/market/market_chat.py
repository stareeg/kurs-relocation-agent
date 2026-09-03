"""Репозиторий чата по ситуации на рынке (вкладка «Рынок», внизу под графиками).

Лента реплик user/assistant на аккаунт (без vacancy-ключа — разговор один на аккаунт про
ситуацию на рынке в целом). История переживает переход между разделами и перезагрузку.
Заменил бывший блок «Что сделать» (next-steps): вместо односторонней сводки от LLM —
свободный диалог с карьерным стратегом по своей ситуации.

Паритет с чатом по вакансии (Заход 6, п.7, миграция 0115): ответ на сообщение
(`reply_to_message_id`, зеркало `hr_messages`) и вложения (`market_chat_message_attachments`,
зеркало `prep_chat_message_attachments`) — до этой миграции ни того, ни другого не было.

Зеркало `core/domains/assistant/resume_chat.py`: минимум зависимостей, нет PG → методы
деградируют (load → [], append → Exception, который роутер ловит — чат без персиста не
должен терять реплики).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool, row_to_dict

ChatRole = Literal["user", "assistant"]

_CHAT_COLS = "id, account_id, role, content, reply_to_message_id, created_at"


class MarketChatMessage(BaseModel):
    id: int | None = None
    account_id: int
    role: ChatRole
    content: str
    reply_to_message_id: int | None = None
    created_at: datetime | None = None


async def load_market_chat(
    *, account_id: int, limit: int = 200, db: Executor | None = None
) -> list[MarketChatMessage]:
    """История чата по ситуации на рынке аккаунта запроса (хронологически). Нет PG → []."""
    db = db or get_pool()
    capped = min(max(limit, 1), 500)
    rows = await db.fetch(
        f"select {_CHAT_COLS} from market_chat_messages where account_id = $1 "
        "order by created_at asc, id asc limit $2",
        account_id,
        capped,
    )
    return [MarketChatMessage(**row_to_dict(r)) for r in rows]


async def append_market_chat(
    *,
    account_id: int,
    role: ChatRole,
    content: str,
    reply_to_message_id: int | None = None,
    db: Executor | None = None,
) -> MarketChatMessage:
    """Добавить реплику в чат по ситуации на рынке аккаунта запроса. Возвращает сохранённую запись."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into market_chat_messages (account_id, role, content, reply_to_message_id) "
        f"values ($1, $2, $3, $4) returning {_CHAT_COLS}",
        account_id,
        role,
        content,
        reply_to_message_id,
    )
    assert row is not None
    return MarketChatMessage(**row_to_dict(row))


async def get_market_chat_message(
    message_id: int, *, account_id: int, db: Executor | None = None
) -> MarketChatMessage | None:
    """Одна реплика по id — источник цитаты для «Ответить» (зеркало `hr_threads.get_message`)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_CHAT_COLS} from market_chat_messages where id = $1 and account_id = $2",
        message_id,
        account_id,
    )
    return MarketChatMessage(**row_to_dict(row)) if row is not None else None


async def delete_market_chat_messages(
    message_ids: list[int], *, account_id: int, db: Executor | None = None
) -> int:
    """Удалить реплики по id (выделение → Удалить во фронте, зеркало `hr_threads.delete_message`
    для множественного выбора). Возвращает число удалённых строк."""
    if not message_ids:
        return 0
    db = db or get_pool()
    result = await db.execute(
        "delete from market_chat_messages where account_id = $1 and id = any($2::bigint[])",
        account_id,
        list(message_ids),
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def clear_market_chat(*, account_id: int, db: Executor | None = None) -> int:
    """Полностью очистить чат по ситуации на рынке аккаунта запроса. Возвращает число удалённых строк."""
    db = db or get_pool()
    result = await db.execute(
        "delete from market_chat_messages where account_id = $1",
        account_id,
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


__all__ = [
    "ChatRole",
    "MarketChatMessage",
    "append_market_chat",
    "clear_market_chat",
    "delete_market_chat_messages",
    "get_market_chat_message",
    "load_market_chat",
]
