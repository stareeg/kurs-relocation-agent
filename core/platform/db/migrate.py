"""Раннер SQL-миграций (задача 1.1, подшаг 2): нумерованные файлы из migrations/.

Каждый ещё не применённый файл прогоняется в отдельной транзакции, имя пишется в
schema_migrations. Идемпотентно: повторный запуск применяет только новое.

CLI: uv run python -m core.platform.db.migrate
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg

from core.config import get_settings
from core.platform.db.pool import create_pool
from core.platform.observability import ensure_utf8_console, event, setup_logging

logger = logging.getLogger(__name__)

_SCHEMA_MIGRATIONS_DDL = """
create table if not exists schema_migrations (
    filename   text primary key,
    applied_at timestamptz not null default now()
)
"""


def _migration_files(migrations_dir: str | Path | None = None) -> list[Path]:
    mig_dir = Path(migrations_dir or get_settings().migrations_dir)
    return sorted(mig_dir.glob("*.sql"))


def migration_numbers(migrations_dir: str | Path | None = None) -> list[int]:
    """Номера файлов в `migrations/` — сверка с `schema_migrations` в админке (Этап 2.1)."""
    numbers: list[int] = []
    for path in _migration_files(migrations_dir):
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit():
            numbers.append(int(prefix))
    return numbers


async def apply_migrations(
    pool: asyncpg.Pool, migrations_dir: str | Path | None = None
) -> list[str]:
    """Применить непринятые миграции по порядку. Возвращает имена применённых файлов."""
    files = _migration_files(migrations_dir)
    applied: list[str] = []
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA_MIGRATIONS_DDL)
        done = {r["filename"] for r in await conn.fetch("select filename from schema_migrations")}
        for path in files:
            if path.name in done:
                continue
            sql = path.read_text(encoding="utf-8")
            try:
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "insert into schema_migrations (filename) values ($1)", path.name
                    )
            except Exception as exc:  # noqa: BLE001 — пишем в бандл до проброса
                event(
                    logger,
                    "БД",
                    "миграция не применилась: %s: %s",
                    path.name,
                    exc,
                    level=logging.ERROR,
                    exc_info=True,
                    migration=path.name,
                )
                raise
            applied.append(path.name)
            event(logger, "БД", "миграция применена: %s", path.name)
    return applied


async def _run() -> None:
    event(logger, "БД", "миграции: старт")
    files = _migration_files()
    if not files:
        event(logger, "БД", "миграций не найдено в %s/", get_settings().migrations_dir)
        return
    pool = await create_pool()
    applied: list[str] = []
    try:
        applied = await apply_migrations(pool)
    except Exception as exc:  # noqa: BLE001 — итоговый фейл CLI тоже в файл
        event(
            logger,
            "БД",
            "миграции упали: %s",
            exc,
            level=logging.ERROR,
            exc_info=True,
        )
        raise
    finally:
        await pool.close()
    if applied:
        event(logger, "БД", "применено миграций: %d", len(applied))
    else:
        event(logger, "БД", "миграции уже применены, изменений нет")


def main() -> None:
    # FR2-72: до любых print/логов — иначе на cp1251 кириллица в event() кракозябры/падение.
    ensure_utf8_console()
    setup_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
