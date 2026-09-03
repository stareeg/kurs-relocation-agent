"""TG-адаптер калибровки: доменный пайплайн + подсказки из BotSettings."""

from __future__ import annotations

from bot_app.config import get_bot_settings
from core.domains.market.salary_calib_pipeline import (
    analyze_report,
    enqueue_if_salary_post,
    process_pending_queue,
)
from core.domains.market.salary_calib_pipeline import (
    status_text as _domain_status_text,
)

__all__ = [
    "analyze_report",
    "enqueue_if_salary_post",
    "process_pending_queue",
    "status_text",
]


async def status_text() -> str:
    s = get_bot_settings()
    return await _domain_status_text(
        auto=s.salary_calib_auto,
        debounce_sec=s.salary_calib_debounce_sec,
        min_pending=s.salary_calib_min_pending,
    )
