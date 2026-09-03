"""Кэш готовых снапшотов «Рынка»: фон считает по расписанию, роутер отдаёт мгновенно.

Один снимок на (`account_id`, `kind`) (`grid` / `pulse` / `search`), upsert из
`snapshot_refresh.py`. LLM-сводка «Ситуация» — свой отдельный append-only кэш
(`situation_store.py`, уже был снапшотом до этого шага), сюда не идёт.

M5 (plans/multitenancy_gaps_2026_08_06.md §3.6): ключ был голым `kind` — один кэш на всю
систему, аккаунты перезатирали друг другу снимок и каждый видел аналитику по чужой воронке (S1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from core.platform.db.pool import Executor, get_pool, row_to_dict


class AnalyticsSnapshot(BaseModel):
    """Один закэшированный срез: `kind` + сериализованная модель + момент расчёта."""

    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    computed_at: datetime


def _snapshot_key(kind: str, days: int | None) -> str:
    """Ключ строки снимка: суффикс окна воронки. `None`/`0` (= «всё») не добавляет
    суффикс — сохраняет ключ фонового пересчёта (`snapshot_refresh.py`) без окна как есть,
    иначе разные периоды затирали бы друг друга в одной строке `kind`."""
    return kind if not days else f"{kind}:{days}"


async def save_snapshot(
    kind: str,
    payload: dict[str, Any],
    *,
    account_id: int,
    days: int | None = None,
    db: Executor | None = None,
) -> None:
    """Upsert снимка аккаунта. Ошибка (нет PG/таблицы) не должна ронять фоновую задачу — только
    логируется вызывающим (`snapshot_refresh.py`)."""
    db = db or get_pool()
    await db.execute(
        "insert into market_analytics_snapshot (account_id, kind, payload, computed_at) "
        "values ($1, $2, $3, now()) "
        "on conflict (account_id, kind) do update set "
        "payload = excluded.payload, computed_at = excluded.computed_at",
        account_id,
        _snapshot_key(kind, days),
        payload,
    )


async def load_snapshot(
    kind: str, *, account_id: int, days: int | None = None, db: Executor | None = None
) -> AnalyticsSnapshot | None:
    """Последний снимок аккаунта по `kind`+окну. Нет строки/нет PG → None (роутер фолбэкает на
    live-расчёт)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select kind, payload, computed_at from market_analytics_snapshot "
        "where account_id = $1 and kind = $2",
        account_id,
        _snapshot_key(kind, days),
    )
    return AnalyticsSnapshot(**row_to_dict(row)) if row is not None else None


async def touch_snapshot(
    kind: str, *, account_id: int, days: int | None = None, db: Executor | None = None
) -> None:
    """Продлить `computed_at` без пересчёта payload: тик без изменений входа не должен
    выглядеть на фронте «протухшим», хотя ничего не пересчитывалось. Строки ещё нет (кэш ещё не
    бутстрапнут) → no-op, её создаст ближайший полный пересчёт."""
    db = db or get_pool()
    await db.execute(
        "update market_analytics_snapshot set computed_at = now() "
        "where account_id = $1 and kind = $2",
        account_id,
        _snapshot_key(kind, days),
    )


__all__ = ["AnalyticsSnapshot", "load_snapshot", "save_snapshot", "touch_snapshot"]
