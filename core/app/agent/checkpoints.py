"""Чекпойнтеры графа агента (A-1/A-3).

Граф собирается с чекпойнтером снаружи: тестам хватает MemorySaver, запуску —
стандартный `AsyncPostgresSaver` (langgraph-checkpoint-postgres, psycopg v3; второй
драйвер, только для таблиц чекпойнтов — продукт живёт на asyncpg). Таблицы создаёт
`setup()` (идемпотентно); владелец lifecycle делает это один раз при старте (A-3).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.memory import MemorySaver


def memory_checkpointer() -> MemorySaver:
    """Чекпойнтер в памяти процесса: юнит-тесты и демо без БД."""
    return MemorySaver()


@asynccontextmanager
async def open_postgres_checkpointer(
    dsn: str | None = None,
) -> AsyncIterator[object]:
    """Живой чекпойнтер в Postgres с созданием таблиц (A-3 поднимет его в lifespan).

    Возвращает saver только внутри `async with`: под ним держится свой пул psycopg.
    По умолчанию DSN из настроек продукта (`settings.postgres_dsn()`).
    """
    from langgraph.checkpoint.postgres.aio import (
        AsyncPostgresSaver,  # отложенный импорт: psycopg тянет либу libpq
    )

    from core.platform.config.settings import get_settings

    resolved = dsn or get_settings().postgres_dsn()
    async with AsyncPostgresSaver.from_conn_string(resolved) as saver:
        await saver.setup()
        yield saver


__all__ = ["memory_checkpointer", "open_postgres_checkpointer"]
