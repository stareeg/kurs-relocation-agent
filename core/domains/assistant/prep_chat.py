"""Репозиторий чата подготовки по вакансии (вкладка «Технички», режим «Подготовка»).

Лента реплик user/assistant, накопительная — общий чат для всех этапов под вакансией.
История переживает перезагрузку и переиспользуется. Чат хранит как запросы на новую пачку
вопросов, так и встречные вопросы владельца с ответами ассистента.

Минимум зависимостей: нет PG → методы деградируют (load возвращает [], append поднимает
Exception, который роутер ловит и отдаёт 503 — чат без персиста не должен терять реплики).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool, row_to_dict

ChatRole = Literal["user", "assistant"]

_CHAT_COLS = "id, vacancy_id, role, content, created_at, reply_to_message_id"


class PrepChatMessage(BaseModel):
    id: int | None = None
    vacancy_id: str
    role: ChatRole
    content: str
    created_at: datetime | None = None
    # Реплика-источник (composer «Ответить») — см. reply_to_message_id у hr_messages.
    reply_to_message_id: int | None = None


async def load_prep_chat(
    vacancy_id: str, *, account_id: int, limit: int = 100, db: Executor | None = None
) -> list[PrepChatMessage]:
    """История чата подготовки по вакансии (хронологически). Нет PG → пустой список."""
    db = db or get_pool()
    capped = min(max(limit, 1), 500)
    rows = await db.fetch(
        f"select {_CHAT_COLS} from prep_chat_messages where vacancy_id = $1 and account_id = $2 "
        "order by created_at asc, id asc limit $3",
        vacancy_id,
        account_id,
        capped,
    )
    return [PrepChatMessage(**row_to_dict(r)) for r in rows]


async def append_prep_chat(
    vacancy_id: str,
    role: ChatRole,
    content: str,
    *,
    account_id: int,
    reply_to_message_id: int | None = None,
    db: Executor | None = None,
) -> PrepChatMessage:
    """Добавить реплику в чат подготовки. Возвращает сохранённую запись с id."""
    db = db or get_pool()
    row = await db.fetchrow(
        "insert into prep_chat_messages (account_id, vacancy_id, role, content, "
        "reply_to_message_id) "
        f"values ($1, $2, $3, $4, $5) returning {_CHAT_COLS}",
        account_id,
        vacancy_id,
        role,
        content,
        reply_to_message_id,
    )
    assert row is not None
    return PrepChatMessage(**row_to_dict(row))


async def delete_prep_chat_message(
    vacancy_id: str, message_id: int, *, account_id: int, db: Executor | None = None
) -> bool:
    """Удалить одну реплику чата подготовки (выделение → Удалить во фронте).

    `vacancy_id`/`account_id` в WHERE — атомарная проверка владения: чужой/не той вакансии id
    не удалит.
    """
    db = db or get_pool()
    row = await db.fetchrow(
        "delete from prep_chat_messages where id = $1 and vacancy_id = $2 and account_id = $3 "
        "returning id",
        message_id,
        vacancy_id,
        account_id,
    )
    return row is not None


async def clear_prep_chat(vacancy_id: str, *, account_id: int, db: Executor | None = None) -> int:
    """Полностью очистить чат подготовки по вакансии. Возвращает число удалённых строк."""
    db = db or get_pool()
    result = await db.execute(
        "delete from prep_chat_messages where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    # asyncpg возвращает "DELETE N" — достаём N.
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
