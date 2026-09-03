"""Дневной лимит автооткликов (2.7) — без новой таблицы.

Считаем через `application_stages` (тот же A-27 Channel-паттерн, что у остальных источников
стадий): `source = "auto_apply_<platform>"`, стадия «Отклик», сегодняшняя дата. Раннер
(расширение) спрашивает счётчик перед взятием следующего кандидата и останавливается на cap.
"""

from __future__ import annotations

from core.domains.pipeline.auto_apply.config import AutoApplyPlatform
from core.kernel.schemas.funnel import FunnelStatus
from core.platform.db.pool import Executor, get_pool


def auto_apply_source(platform: AutoApplyPlatform) -> str:
    """Канон `application_stages.source` для автооткликов одной площадки."""
    return f"auto_apply_{platform}"


async def count_today(
    platform: AutoApplyPlatform, *, account_id: int, db: Executor | None = None
) -> int:
    """Сколько автооткликов этой площадки уже ушло сегодня (по времени БД)."""
    executor = db or get_pool()
    row = await executor.fetchrow(
        "select count(*) as n from application_stages "
        "where account_id = $1 and source = $2 and stage = $3 "
        "and changed_at::date = current_date",
        account_id,
        auto_apply_source(platform),
        FunnelStatus.APPLIED.value,
    )
    return int(row["n"]) if row else 0


__all__ = ["auto_apply_source", "count_today"]
