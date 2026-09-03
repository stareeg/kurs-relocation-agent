"""Single-flight: параллельные одинаковые запросы делят один in-flight Task.

Подключается в `call.run`. Двойной клик / две вкладки с тем же ключом → один LLM.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

T = TypeVar("T")


class SingleFlight:
    """In-memory single-flight по строковому ключу.

    Пока живёт первый вызов — остальные с тем же ключом ждут его результат.
    Ошибка первого пробрасывается всем ждущим; ключ снимается, когда Task завершён.
    """

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._lock = asyncio.Lock()

    @property
    def inflight_count(self) -> int:
        """Число ключей in-flight (для тестов/диагностики)."""
        return len(self._inflight)

    async def do(
        self,
        key: str,
        factory: Callable[[], Coroutine[Any, Any, T] | Awaitable[T]],
    ) -> T:
        async with self._lock:
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(_invoke(factory))
                self._inflight[key] = task

        try:
            return await task  # type: ignore[no-any-return]
        finally:
            async with self._lock:
                current = self._inflight.get(key)
                if current is task and task.done():
                    del self._inflight[key]


async def _invoke(factory: Callable[[], Coroutine[Any, Any, T] | Awaitable[T]]) -> T:
    return await factory()  # type: ignore[return-value]


_DEFAULT: SingleFlight | None = None


def get_single_flight() -> SingleFlight:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = SingleFlight()
    return _DEFAULT


def set_single_flight_for_tests(flight: SingleFlight | None) -> None:
    """Подмена/сброс глобального single-flight в тестах."""
    global _DEFAULT
    _DEFAULT = flight


def reset_single_flight_for_tests() -> None:
    set_single_flight_for_tests(None)
