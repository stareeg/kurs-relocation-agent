"""Репозиторий пресетов discovery (имя → search-URL hh.ru) — PG-замена JSON-файлу.

Раньше жил в `data/discovery_presets.json` (`bot_app/storage/discovery_presets.py`).
Перенесён в Postgres (миграция 0034, таблица `discovery_presets`), чтобы не держать папку `data/`.
upsert по (account_id, name) — один пресет на аккаунт. read-only по смыслу HH — это сохранённые
поисковые ссылки.

M5 (plans/multitenancy_gaps_2026_08_06.md §6): раньше пресеты были общими на всю систему —
друг видел и мог удалить чужие сохранённые поиски (S2/S1).
"""

from __future__ import annotations

import logging

from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)


async def list_all(*, account_id: int, db: Executor | None = None) -> dict[str, str]:
    db = db or get_pool()
    rows = await db.fetch(
        "select name, url from discovery_presets where account_id = $1 order by name",
        account_id,
    )
    return {r["name"]: r["url"] for r in rows}


async def get(name: str, *, account_id: int, db: Executor | None = None) -> str | None:
    if not name:
        return None
    db = db or get_pool()
    return await db.fetchval(
        "select url from discovery_presets where account_id = $1 and name = $2",
        account_id,
        name,
    )


async def add(name: str, url: str, *, account_id: int, db: Executor | None = None) -> None:
    """Сохранить/обновить пресет аккаунта (upsert). Пустые имя/URL — ValueError."""
    name = (name or "").strip()
    url = (url or "").strip()
    if not name or not url:
        raise ValueError("нужны и имя, и URL пресета")
    db = db or get_pool()
    await db.execute(
        "insert into discovery_presets (account_id, name, url, updated_at) "
        "values ($1, $2, $3, now()) "
        "on conflict (account_id, name) do update set url = excluded.url, updated_at = now()",
        account_id,
        name,
        url,
    )


async def remove(name: str, *, account_id: int, db: Executor | None = None) -> bool:
    """Удалить пресет аккаунта. True — был и удалён, False — не было."""
    if not name:
        return False
    db = db or get_pool()
    result = await db.execute(
        "delete from discovery_presets where account_id = $1 and name = $2", account_id, name
    )
    # asyncpg возвращает "DELETE N" — N это кол-во удалённых строк
    return _rows_affected(result) > 0


def _rows_affected(status: str | None) -> int:
    if not status:
        return 0
    parts = status.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0


__all__ = ["list_all", "get", "add", "remove"]
