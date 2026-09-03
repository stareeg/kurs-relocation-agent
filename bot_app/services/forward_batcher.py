"""Debounce-батчер пересылок: generic ``push(chat_id, item, on_batch)``.

Собирает элементы одного чата за окно ``debounce_sec`` (по умолчанию 4.5 с),
затем один раз зовёт ``on_batch(items)``. При достижении ``max_items`` (30) —
flush сразу, без ожидания окна. HR и вакансии держат отдельные экземпляры.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

OnBatchFn = Callable[[list[T]], Awaitable[None]]

DEFAULT_DEBOUNCE_SEC = 4.5
DEFAULT_MAX_ITEMS = 30


class ForwardBatcher(Generic[T]):
    """Чистый asyncio-debounce без зависимостей: окно + cap на чат."""

    def __init__(
        self,
        *,
        debounce_sec: float = DEFAULT_DEBOUNCE_SEC,
        max_items: int = DEFAULT_MAX_ITEMS,
        name: str = "forward",
    ) -> None:
        if debounce_sec <= 0:
            raise ValueError("debounce_sec must be > 0")
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        self.debounce_sec = debounce_sec
        self.max_items = max_items
        self.name = name
        self._items: dict[int, list[T]] = {}
        self._on_batch: dict[int, OnBatchFn[T]] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, chat_id: int) -> asyncio.Lock:
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def _cancel_timer(self, chat_id: int) -> None:
        old = self._tasks.pop(chat_id, None)
        if old and not old.done():
            old.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await old

    async def push(self, chat_id: int, item: T, on_batch: OnBatchFn[T]) -> None:
        """Добавить элемент в бакет чата; сбросить debounce-таймер (или flush по cap)."""
        self._items.setdefault(chat_id, []).append(item)
        self._on_batch[chat_id] = on_batch

        await self._cancel_timer(chat_id)

        if len(self._items.get(chat_id, [])) >= self.max_items:
            await self._flush(chat_id)
            return

        self._tasks[chat_id] = asyncio.create_task(self._delayed_flush(chat_id))

    async def _delayed_flush(self, chat_id: int) -> None:
        await asyncio.sleep(self.debounce_sec)
        await self._flush(chat_id)

    async def _flush(self, chat_id: int) -> None:
        async with self._lock(chat_id):
            items = self._items.pop(chat_id, [])
            on_batch = self._on_batch.pop(chat_id, None)
            self._tasks.pop(chat_id, None)

        if not items or on_batch is None:
            return

        logger.info("%s batch: chat=%s items=%d", self.name, chat_id, len(items))
        await on_batch(items)
