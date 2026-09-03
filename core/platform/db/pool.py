"""asyncpg-пул (задача 1.1, подшаг 3): единый коннект-пул, lifespan-инициализация в API.

jsonb/json кодеки ставим на каждый коннект: параметры-словари сериализуются json.dumps,
строки-результаты десериализуются json.loads — repository работает с dict, а не str.

L-01: глобальный пул оборачивается в `TimingPool` — копит db_ms в Server-Timing.
Методы asyncpg.Connection read-only, поэтому не патчим connection, а проксируем вызовы.

L-31: min_size поднят с 1 до 4 (`DbSettings.postgres_pool_min_size`) — первые запросы
после старта не платят за установление соединения (TCP+auth), см. `create_pool()`.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

import asyncpg

from core.config import get_settings
from core.platform.observability import event
from core.platform.observability.request_timing import record_db_ms

logger = logging.getLogger(__name__)


class Executor(Protocol):
    """SQL-поверхность, общая для Pool/Connection у asyncpg (и их Timing-прокси).

    Repository принимает любой из них (pool в проде, connection в транзакциях/тестах) —
    структурный Protocol вместо `Any`, чтобы `db = db or get_pool()` narrow-ился в
    pyright (иначе `Any | None` не теряет `None` после `or`, см. `db: Executor | None`
    во всех repo.py — были ложные reportOptionalMemberAccess на каждый вызов).
    """

    async def fetch(self, *args: Any, **kwargs: Any) -> Any: ...
    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any: ...
    async def fetchval(self, *args: Any, **kwargs: Any) -> Any: ...
    async def execute(self, *args: Any, **kwargs: Any) -> Any: ...
    async def executemany(self, *args: Any, **kwargs: Any) -> Any: ...


_pool: Any | None = None


def row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """asyncpg.Record → dict для Pydantic (явный проход по keys — pyright не теряет тип)."""
    # .keys() обязателен: итерация по самой Record отдаёт значения, не имена колонок (не dict).
    return {key: row[key] for key in row.keys()}  # noqa: SIM118


async def _db_timed(awaitable: Any) -> Any:
    started = time.perf_counter()
    try:
        return await awaitable
    finally:
        record_db_ms((time.perf_counter() - started) * 1000)


class TimingConnection:
    """Прокси connection: SQL-методы с учётом db_ms."""

    __slots__ = ("_conn",)

    def __init__(self, conn: Any) -> None:
        # asyncpg: Pool.acquire → Connection | PoolConnectionProxy
        object.__setattr__(self, "_conn", conn)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    @property
    def raw(self) -> Any:
        return self._conn

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._conn.fetch(*args, **kwargs))

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._conn.fetchrow(*args, **kwargs))

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._conn.fetchval(*args, **kwargs))

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._conn.execute(*args, **kwargs))

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._conn.executemany(*args, **kwargs))


def _unwrap_conn(connection: Any) -> Any:
    if isinstance(connection, TimingConnection):
        return connection.raw
    return connection


class _TimingAcquire:
    """Совместимо с `await pool.acquire()` и `async with pool.acquire()`."""

    def __init__(self, pool: asyncpg.Pool, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self._pool = pool
        self._args = args
        self._kwargs = kwargs
        self._conn: Any = None

    def __await__(self):
        return self._acquire().__await__()

    async def _acquire(self) -> TimingConnection:
        conn = await self._pool.acquire(*self._args, **self._kwargs)
        return TimingConnection(conn)

    async def __aenter__(self) -> TimingConnection:
        self._conn = await self._pool.acquire(*self._args, **self._kwargs)
        return TimingConnection(self._conn)

    async def __aexit__(self, *exc: object) -> None:
        if self._conn is not None:
            await self._pool.release(self._conn)
            self._conn = None


class TimingPool:
    """Прокси asyncpg.Pool с учётом db_ms на SQL и acquire."""

    __slots__ = ("_pool",)

    def __init__(self, pool: asyncpg.Pool) -> None:
        object.__setattr__(self, "_pool", pool)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pool, name)

    @property
    def raw(self) -> asyncpg.Pool:
        return self._pool

    def acquire(self, *args: Any, **kwargs: Any) -> _TimingAcquire:
        return _TimingAcquire(self._pool, args, kwargs)

    async def release(self, connection: Any, *args: Any, **kwargs: Any) -> None:
        await self._pool.release(_unwrap_conn(connection), *args, **kwargs)

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._pool.fetch(*args, **kwargs))

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._pool.fetchrow(*args, **kwargs))

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._pool.fetchval(*args, **kwargs))

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._pool.execute(*args, **kwargs))

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        return await _db_timed(self._pool.executemany(*args, **kwargs))

    async def close(self) -> None:
        await self._pool.close()


async def _init_connection(conn: asyncpg.Connection) -> None:
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def create_pool(
    dsn: str | None = None,
    *,
    min_size: int | None = None,
    max_size: int | None = None,
    command_timeout: float | None = None,
) -> asyncpg.Pool:
    """Создать новый пул (не трогает глобальный) — для тестовой БД и CLI.

    command_timeout — потолок asyncpg на один запрос через пул; без него зависший запрос
    (например при заблокированной строке) висит бесконечно, а не падает с ошибкой.
    min_size — L-31: asyncpg подключает столько коннектов синхронно прямо здесь (до
    возврата из `await create_pool()`), так что дефолт из настроек уже и есть прогрев пула.
    """
    settings = get_settings()
    dsn = dsn or settings.postgres_dsn()
    if min_size is None:
        min_size = settings.postgres_pool_min_size
    if max_size is None:
        max_size = settings.postgres_pool_max_size
    if command_timeout is None:
        command_timeout = settings.postgres_command_timeout_s
    return await asyncpg.create_pool(
        dsn,
        init=_init_connection,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
    )


async def init_pool() -> TimingPool:
    """Поднять глобальный пул один раз (идемпотентно). Зовётся из lifespan API."""
    global _pool
    if _pool is None:
        try:
            raw = await create_pool()
            _pool = TimingPool(raw)
        except Exception as exc:
            event(
                logger,
                "БД",
                "пул Postgres не поднялся: %s. Проверь нативный PostgreSQL 18 на 127.0.0.1:5432 (служба postgresql-x64-18)",
                exc,
                level=logging.WARNING,
            )
            raise
        event(
            logger,
            "БД",
            "пул Postgres поднят (прогрето %d/%d коннектов)",
            raw.get_size(),
            raw.get_max_size(),
        )
    return _pool


def get_pool() -> TimingPool:
    """Глобальный пул; падает, если не инициализирован (lifespan не отработал)."""
    if _pool is None:
        raise RuntimeError("Postgres pool не инициализирован — вызови init_pool() в lifespan API")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        event(logger, "БД", "пул Postgres закрыт")


async def table_exists(table_name: str, *, db: Executor | None = None) -> bool:
    """True — таблица `table_name` существует (без учёта прав доступа текущей роли).

    Нужна db-тестам, которые зависят от свежих миграций: `@pytest.mark.db` тесты
    должны скипаться без таблицы, а не падать с `UndefinedTableError` (см. 0125/0126).
    """
    executor = db or get_pool()
    row = await executor.fetchrow(
        "select exists(select 1 from information_schema.tables where table_name = $1) as ex",
        table_name,
    )
    return bool(row["ex"]) if row else False
