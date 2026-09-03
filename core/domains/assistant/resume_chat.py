"""Репозиторий чата по резюме (вкладка «Резюме», под ResumeScoreCard).

Лента реплик user/assistant на аккаунт (без vacancy-ключа — резюме у аккаунта одно, разговор общий).
История переживает переход между разделами и перезагрузку. Хранит как запросы владельца на
усиление блоков, так и ответы ассистента с готовыми формулировками.

Минимум зависимостей: нет PG → методы деградируют (load возвращает [], append поднимает
Exception, который роутер ловит — чат без персиста не должен терять реплики).

Паритет с чатом по вакансии (Заход 6, п.7, миграция 0120): ответ на сообщение
(`reply_to_message_id`, зеркало `hr_messages`) и вложения (`resume_chat_message_attachments`,
зеркало `prep/market_chat_message_attachments`) — до миграции 0120 ни того, ни другого не было.

Зеркало `core/domains/market/market_chat.py`: минимум зависимостей, нет PG → методы
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


class ResumeChatMessage(BaseModel):
    id: int | None = None
    account_id: int
    role: ChatRole
    content: str
    reply_to_message_id: int | None = None
    created_at: datetime | None = None


async def load_resume_chat(
    *, account_id: int, limit: int = 200, db: Executor | None = None
) -> list[ResumeChatMessage]:
    """История чата по резюме аккаунта запроса (хронологически). Нет PG → пустой список."""
    db = db or get_pool()
    capped = min(max(limit, 1), 500)
    rows = await db.fetch(
        f"select {_CHAT_COLS} from resume_chat_messages where account_id = $1 "
        "order by created_at asc, id asc limit $2",
        account_id,
        capped,
    )
    return [ResumeChatMessage(**row_to_dict(r)) for r in rows]


async def append_resume_chat(
    *,
    account_id: int,
    role: ChatRole,
    content: str,
    reply_to_message_id: int | None = None,
    db: Executor | None = None,
) -> ResumeChatMessage:
    """Добавить реплику в чат по резюме аккаунта запроса. Возвращает сохранённую запись с id."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into resume_chat_messages (account_id, role, content, reply_to_message_id) "
        f"values ($1, $2, $3, $4) returning {_CHAT_COLS}",
        account_id,
        role,
        content,
        reply_to_message_id,
    )
    assert row is not None
    return ResumeChatMessage(**row_to_dict(row))


async def get_resume_chat_message(
    message_id: int, *, account_id: int, db: Executor | None = None
) -> ResumeChatMessage | None:
    """Одна реплика по id — источник цитаты для «Ответить» (зеркало `market_chat.get_message`)."""
    db = db or get_pool()
    row = await db.fetchrow(
        f"select {_CHAT_COLS} from resume_chat_messages where id = $1 and account_id = $2",
        message_id,
        account_id,
    )
    return ResumeChatMessage(**row_to_dict(row)) if row is not None else None


async def delete_resume_chat_messages(
    message_ids: list[int], *, account_id: int, db: Executor | None = None
) -> int:
    """Удалить реплики по id (выделение → Удалить во фронте, зеркало `market_chat.delete_messages`
    для множественного выбора). Возвращает число удалённых строк."""
    if not message_ids:
        return 0
    db = db or get_pool()
    result = await db.execute(
        "delete from resume_chat_messages where account_id = $1 and id = any($2::bigint[])",
        account_id,
        list(message_ids),
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


async def clear_resume_chat(*, account_id: int, db: Executor | None = None) -> int:
    """Полностью очистить чат по резюме аккаунта запроса. Возвращает число удалённых строк."""
    db = db or get_pool()
    result = await db.execute(
        "delete from resume_chat_messages where account_id = $1",
        account_id,
    )
    # asyncpg возвращает "DELETE N" — достаём N.
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0


__all__ = [
    "ChatRole",
    "ResumeChatMessage",
    "append_resume_chat",
    "clear_resume_chat",
    "delete_resume_chat_messages",
    "get_resume_chat_message",
    "load_resume_chat",
]
