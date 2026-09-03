"""Э14: GC простаивающих столов + уборка пустых WS-сессий в хабе.

Столы open|playing без касаний `updated_at` дольше TTL закрываются.
Живой хаб: drop_if_empty для комнат без коннектов (после ended/reveal или лобби).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.multiplayer import repo
from core.platform.observability import event
from core.platform.tasks import enqueue, get_runtime, register_handler

logger = logging.getLogger(__name__)

MULTIPLAYER_IDLE_GC_KIND = "multiplayer_idle_gc"
# Чаще TTL, чтобы брошенный стол не висел лишние часы после дедлайна.
MULTIPLAYER_IDLE_GC_INTERVAL_SEC = 15 * 60
# Нет фазы/WS-тиков → updated_at не двигается.
IDLE_ROOM_TTL_HOURS = 2.0
_BATCH_SIZE = 50


def _bucket_key(*, at: datetime, interval_sec: int) -> str:
    epoch = int(at.timestamp())
    bucket = epoch - (epoch % interval_sec)
    return f"{MULTIPLAYER_IDLE_GC_KIND}:{bucket}"


async def close_idle_rooms(*, older_than_hours: float = IDLE_ROOM_TTL_HOURS) -> int:
    """Закрыть idle-столы в PG и выкинуть их из WS-хаба. Возвращает число закрытых."""
    from core.domains.multiplayer.session import hub

    closed = 0
    while True:
        batch = await repo.list_idle_room_ids(older_than_hours=older_than_hours, limit=_BATCH_SIZE)
        if not batch:
            break
        for room in batch:
            rid = int(room["id"])
            code = str(room["code"])
            row = await repo.close_room(rid)
            if row is None:
                continue
            closed += 1
            try:
                await hub().force_close(code, detail="Стол закрыт: долго без активности")
            except Exception:  # noqa: BLE001
                logger.exception("mp_idle_gc_hub_failed code=%s", code)
        if len(batch) < _BATCH_SIZE:
            break
    return closed


async def sweep_empty_hub_sessions() -> int:
    """Убрать из памяти сессии без коннектов (ended / пустой лобби)."""
    from core.domains.multiplayer.session import hub

    h = hub()
    codes = h.room_codes()
    dropped = 0
    for code in codes:
        before = h.get(code)
        if before is None:
            continue
        await h.drop_if_empty(code)
        if h.get(code) is None:
            dropped += 1
    return dropped


async def run_idle_gc() -> dict[str, int]:
    closed = await close_idle_rooms()
    swept = await sweep_empty_hub_sessions()
    if closed or swept:
        event(
            logger,
            "ЗАДАЧА",
            "mp_idle_gc closed=%s hub_swept=%s",
            closed,
            swept,
            closed=closed,
            hub_swept=swept,
        )
    return {"closed": closed, "hub_swept": swept}


async def _run_idle_gc_task(_payload: Mapping[str, Any]) -> None:
    try:
        await run_idle_gc()
    finally:
        next_run = datetime.now(UTC) + timedelta(seconds=MULTIPLAYER_IDLE_GC_INTERVAL_SEC)
        await enqueue(
            MULTIPLAYER_IDLE_GC_KIND,
            run_at=next_run,
            idempotency_key=_bucket_key(at=next_run, interval_sec=MULTIPLAYER_IDLE_GC_INTERVAL_SEC),
            priority=155,
        )


async def register_multiplayer_idle_gc_schedule() -> None:
    """Handler + первая задача в очереди (если цепочки ещё нет)."""
    register_handler(MULTIPLAYER_IDLE_GC_KIND, _run_idle_gc_task)
    if not await get_runtime().store.has_pending_of_kind(MULTIPLAYER_IDLE_GC_KIND):
        now = datetime.now(UTC)
        await enqueue(
            MULTIPLAYER_IDLE_GC_KIND,
            run_at=now,
            idempotency_key=_bucket_key(at=now, interval_sec=MULTIPLAYER_IDLE_GC_INTERVAL_SEC),
            priority=155,
        )
    event(
        logger,
        "ЗАПУСК",
        "GC idle-столов мультиплеера: каждые %sс, TTL %sч",
        MULTIPLAYER_IDLE_GC_INTERVAL_SEC,
        IDLE_ROOM_TTL_HOURS,
    )


__all__ = [
    "IDLE_ROOM_TTL_HOURS",
    "MULTIPLAYER_IDLE_GC_INTERVAL_SEC",
    "MULTIPLAYER_IDLE_GC_KIND",
    "close_idle_rooms",
    "register_multiplayer_idle_gc_schedule",
    "run_idle_gc",
    "sweep_empty_hub_sessions",
]
