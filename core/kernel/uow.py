"""Unit of Work: атомарная граница записи для сценариев с несколькими таблицами.

Домен не открывает транзакции сам и не знает про asyncpg: сценарий делает
``async with ports.uow() as uow:`` и передаёт ``uow.session`` в репозиторий (Protocol).
Выход с исключением → откат; нормальный выход → commit.

Модуль без I/O: только Protocol (правило слоя ``kernel``). Реализации —
``core/app/uow.py``, связываются в ``wiring.wire_default_ports``.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable


@runtime_checkable
class UnitOfWork(Protocol):
    """Граница транзакции: либо все записи сценария, либо ничего.

    ``session`` — исполнитель запросов внутри этой границы. В проде это connection
    Postgres; в тестах — in-memory store. Репозиторий домена принимает его как ``db``.
    """

    @property
    def session(self) -> Any: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


__all__ = ["UnitOfWork"]
