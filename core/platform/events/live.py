"""Живая рассылка доменных событий: фронт меняет поллинг на инвалидацию по SSE.

Один постоянный подписчик шины на базовый `DomainEvent` — не по подписке на каждый
тип: список событий первой очереди уже есть (`kernel/events.py`), фронт сам решает, какие
query keys инвалидировать по имени события, править бэк под новый экран не нужно.

Раздача — по одной `asyncio.Queue` на открытое SSE-соединение, с привязанным `account_id`
(plans/multitenancy_gaps_2026_08_06.md §3.12): раньше это было `set[Queue]` без личности,
и каждое доменное событие ЛЮБОГО аккаунта уходило ВСЕМ открытым вкладкам вместе с subject
(vacancy_id) и полями — утечка метаданных активности. Теперь `broadcast` фильтрует по
совпадению account_id события и подписчика.

`platform` не знает типов `core.kernel.events` (правило слоя 1) — событие принимается
структурно, как в `journal.py`: `name` / `subject` / `to_fields()`. account_id события берём
так же структурно (`getattr`), с фолбэком на per-request/per-task ContextVar
(`core.config.current_account_id`) — publish всегда происходит синхронно внутри того же
request/bot-update/task-контекста, что и его причина, так что на момент `broadcast()` ContextVar
ещё несёт личность издателя. Это покрывает и типы событий, у которых поля account_id пока нет
(`ScreeningPackReady`, `AttachmentAnalyzed`) — без правки `core/kernel/events.py`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

from core.config import current_account_id

logger = logging.getLogger(__name__)

#: Очередь одного соединения переполнена (клиент завис/вкладка в фоне) — событие теряется,
#: а не блокирует издателя и не копится безгранично.
_QUEUE_MAXSIZE = 200


def _as_payload(evt: Any) -> dict[str, Any]:
    name = getattr(evt, "name", None) or type(evt).__name__
    subject = getattr(evt, "subject", "") or ""
    fields_fn = getattr(evt, "to_fields", None)
    raw_fields = fields_fn() if callable(fields_fn) else {}
    fields = dict(raw_fields) if isinstance(raw_fields, Mapping) else {}
    return {"type": name, "subject": subject, "fields": fields}


class LiveEventBroadcaster:
    """Fan-out доменных событий во все живые SSE-соединения (без БД, без журнала)."""

    def __init__(self) -> None:
        self._queues: dict[asyncio.Queue[dict[str, Any]], int] = {}

    def register(self, account_id: int) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._queues[queue] = account_id
        return queue

    def unregister(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues.pop(queue, None)

    def broadcast(self, evt: Any) -> None:
        """Колбэк шины: вызывается синхронно на каждой публикации домена.

        Fail-closed: без определённого account_id событие не уходит никому — не
        рассылаем «на всякий случай всем», как было раньше.
        """
        if not self._queues:
            return
        evt_account_id = getattr(evt, "account_id", None) or current_account_id()
        if not evt_account_id:
            return
        payload = _as_payload(evt)
        for queue, account_id in list(self._queues.items()):
            if account_id != evt_account_id:
                continue
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning(
                    "live-events: очередь переполнена, событие %s потеряно", payload["type"]
                )

    async def stream(self, queue: asyncio.Queue[dict[str, Any]]) -> AsyncIterator[dict[str, Any]]:
        """Бесконечный источник для `api.streaming.sse_response` — до отмены (клиент отключился)."""
        try:
            while True:
                yield await queue.get()
        finally:
            self.unregister(queue)

    def connection_count(self) -> int:
        """Число живых SSE-соединений (диагностика)."""
        return len(self._queues)


#: Единственный экземпляр — процесс-синглтон (как `sessions` в `api/security.py`).
broadcaster = LiveEventBroadcaster()

__all__ = ["LiveEventBroadcaster", "broadcaster"]
