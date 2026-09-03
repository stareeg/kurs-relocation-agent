"""GC несвязанных вложений (Э0-5 плана chat_image_attachments): ежедневная задача A-20.

Загрузил скриншот в композер и передумал отправлять (§2.3 плана: черновик = отсутствие связки в
таблице связок сообщения) — строка остаётся в `attachments` без единой связки. Здесь она и
удаляется, если старше `ATTACHMENT_GC_AFTER_HOURS`. `repo.gc_candidates` сам исключает оригиналы,
на которые ссылается `derived_from` живой (кроп) строки, и — как только появится хотя бы одна
таблица связок — строки с живой связкой.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.assistant.attachments import repo
from core.platform.config.settings import get_settings
from core.platform.observability import event
from core.platform.tasks import CronSpec, add_cron, register_handler

logger = logging.getLogger(__name__)

ATTACHMENTS_GC_KIND = "attachments_gc"
ATTACHMENTS_GC_SCHEDULE_ID = "attachments_gc"
_GC_HOUR = 4
_GC_MINUTE = 15
_DAILY_MISFIRE_GRACE_SEC = 3600
# Постранично — кандидатов на удаление может быть больше одной страницы `repo.gc_candidates`.
_BATCH_SIZE = 500


async def _run_attachments_gc(_payload: Mapping[str, Any]) -> None:
    """Удалить несвязанные вложения старше TTL, постранично до полного вычерпывания."""
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().attachment_gc_after_hours)
    total = 0
    while True:
        candidates = await repo.gc_candidates(older_than=cutoff, limit=_BATCH_SIZE)
        if not candidates:
            break
        total += await repo.delete_attachments(candidates)
        if len(candidates) < _BATCH_SIZE:
            break
    if total:
        event(logger, "ЗАДАЧА", "GC вложений: удалено несвязанных строк: %d", total)


async def register_attachments_gc_schedule() -> None:
    """Handler + суточный cron. Зовётся из `core.app.background`, рядом с `register_market_schedules`."""
    register_handler(ATTACHMENTS_GC_KIND, _run_attachments_gc)
    add_cron(
        CronSpec(
            schedule_id=ATTACHMENTS_GC_SCHEDULE_ID,
            hour=_GC_HOUR,
            minute=_GC_MINUTE,
            kind=ATTACHMENTS_GC_KIND,
            priority=140,
            misfire_grace_sec=_DAILY_MISFIRE_GRACE_SEC,
        )
    )
    event(
        logger,
        "ЗАПУСК",
        "GC вложений: ежедневно в %02d:%02d, TTL %sч",
        _GC_HOUR,
        _GC_MINUTE,
        get_settings().attachment_gc_after_hours,
    )


__all__ = [
    "ATTACHMENTS_GC_KIND",
    "ATTACHMENTS_GC_SCHEDULE_ID",
    "register_attachments_gc_schedule",
]
