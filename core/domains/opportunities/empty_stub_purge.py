"""Автоудаление пустых stub-вакансий без скора (синк откликов без текста JD).

Интервал чаще TTL (6 ч), чтобы карточка не висела лишние сутки после дедлайна. Цепочка
сама себя перепланирует — тот же приём, что `market.snapshot_refresh`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.opportunities.jobs import EMPTY_UNSCORED_TTL_HOURS, purge_empty_unscored_jobs
from core.platform.observability import event
from core.platform.tasks import enqueue, get_runtime, register_handler

logger = logging.getLogger(__name__)

EMPTY_STUB_PURGE_KIND = "empty_stub_purge"
EMPTY_STUB_PURGE_INTERVAL_SEC = 30 * 60


def _bucket_key(*, at: datetime, interval_sec: int) -> str:
    epoch = int(at.timestamp())
    bucket = epoch - (epoch % interval_sec)
    return f"{EMPTY_STUB_PURGE_KIND}:{bucket}"


async def _purge_empty_stubs(_payload: Mapping[str, Any]) -> None:
    try:
        n = await purge_empty_unscored_jobs(older_than_hours=EMPTY_UNSCORED_TTL_HOURS)
        if n:
            event(logger, "ЗАДАЧА", "удалены пустые stub-вакансии без скора: %d", n)
    finally:
        next_run = datetime.now(UTC) + timedelta(seconds=EMPTY_STUB_PURGE_INTERVAL_SEC)
        await enqueue(
            EMPTY_STUB_PURGE_KIND,
            run_at=next_run,
            idempotency_key=_bucket_key(at=next_run, interval_sec=EMPTY_STUB_PURGE_INTERVAL_SEC),
            priority=160,
        )


async def register_empty_stub_purge_schedule() -> None:
    """Handler + первая задача в очереди (если цепочки ещё нет)."""
    register_handler(EMPTY_STUB_PURGE_KIND, _purge_empty_stubs)
    if not await get_runtime().store.has_pending_of_kind(EMPTY_STUB_PURGE_KIND):
        now = datetime.now(UTC)
        await enqueue(
            EMPTY_STUB_PURGE_KIND,
            run_at=now,
            idempotency_key=_bucket_key(at=now, interval_sec=EMPTY_STUB_PURGE_INTERVAL_SEC),
            priority=160,
        )
    event(
        logger,
        "ЗАПУСК",
        "шедулер пустых stub'ов: каждые %sс, TTL %sч",
        EMPTY_STUB_PURGE_INTERVAL_SEC,
        EMPTY_UNSCORED_TTL_HOURS,
    )


__all__ = [
    "EMPTY_STUB_PURGE_INTERVAL_SEC",
    "EMPTY_STUB_PURGE_KIND",
    "register_empty_stub_purge_schedule",
]
