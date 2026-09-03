"""Реализации Unit of Work: Postgres и in-memory для тестов.

Домен зовёт ``async with ports.uow() as uow:`` и не знает, какая реализация подставлена.
Связывание — в ``wiring.wire_default_ports``.
"""

from __future__ import annotations

import copy
from types import TracebackType
from typing import Any

import asyncpg

from core.platform.db.pool import get_pool


class PostgresUnitOfWork:
    """UoW поверх asyncpg: acquire connection → transaction → commit/rollback → release.

    ``session`` — сама connection; её можно передать в существующие repo-функции как ``db=``.
    Атрибут (не property): ``runtime_checkable``/hasattr не должен звать геттер до enter.
    """

    def __init__(self, pool: asyncpg.Pool | None = None) -> None:
        self._pool = pool
        # PoolConnectionProxy | Connection — у asyncpg разные типы у acquire/connect.
        self._conn: Any = None
        self._tr: Any = None
        self._owned = False  # connection взяли мы (release в __aexit__)
        self.session: Any = None

    async def __aenter__(self) -> PostgresUnitOfWork:
        pool = self._pool if self._pool is not None else get_pool()
        self._conn = await pool.acquire()
        self._owned = True
        self._tr = self._conn.transaction()
        await self._tr.start()
        self.session = self._conn
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if self._tr is not None:
                if exc_type is None:
                    await self._tr.commit()
                else:
                    await self._tr.rollback()
        finally:
            self._tr = None
            self.session = None
            if self._owned and self._conn is not None:
                pool = self._pool if self._pool is not None else get_pool()
                await pool.release(self._conn)
            self._conn = None
            self._owned = False


class MemoryStore:
    """Простой dict-store для MemoryUnitOfWork: ключ коллекции → id → запись."""

    def __init__(self) -> None:
        self.tables: dict[str, dict[Any, Any]] = {}

    def table(self, name: str) -> dict[Any, Any]:
        return self.tables.setdefault(name, {})

    def clear(self) -> None:
        self.tables.clear()


class MemoryUnitOfWork:
    """In-memory UoW для тестов: рабочая копия store, commit = replace, rollback = discard.

    ``session`` — рабочий ``MemoryStore`` внутри границы. Репозиторий-двойник пишет в него;
    при исключении committed-store не меняется — ровно контракт «нет полузаписи».
    """

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._committed = store if store is not None else MemoryStore()
        self._working: MemoryStore | None = None
        self.session: MemoryStore | None = None

    @property
    def store(self) -> MemoryStore:
        """Committed-store снаружи границы (для ассертов после сценария)."""
        return self._committed

    async def __aenter__(self) -> MemoryUnitOfWork:
        self._working = copy.deepcopy(self._committed)
        self.session = self._working
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None and self._working is not None:
            self._committed.tables = self._working.tables
        self._working = None
        self.session = None


def postgres_uow_factory(pool: asyncpg.Pool | None = None) -> PostgresUnitOfWork:
    """Фабрика для ``ports.bind(uow_factory=...)`` — новый UoW на каждый вызов."""
    return PostgresUnitOfWork(pool=pool)


__all__ = [
    "MemoryStore",
    "MemoryUnitOfWork",
    "PostgresUnitOfWork",
    "postgres_uow_factory",
]
