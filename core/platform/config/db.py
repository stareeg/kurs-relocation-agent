"""DbSettings — инфраструктура Postgres (.env: POSTGRES_*)."""

from __future__ import annotations

from pydantic import BaseModel


class DbSettings(BaseModel):
    """Подключение к Postgres и миграции.

    Дефолты — локальная нативная PostgreSQL 18 (`deploy/init_native_pg.sql`).
    Секреты/хост переопределяются через `.env`, не через код.
    """

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "copilot"
    postgres_password: str = "copilot"
    postgres_db: str = "copilot"
    # sslmode коннекта (asyncpg и psycopg читают его из DSN). Локально без TLS — disable.
    postgres_sslmode: str = "disable"
    # Каталог нумерованных SQL-миграций (раннер core.platform.db.migrate).
    migrations_dir: str = "core/platform/db/migrations"
    # Потолок на один запрос через пул — зависший запрос падает, а не висит вечно.
    postgres_command_timeout_s: float = 20.0
    # L-31: asyncpg открывает min_size коннектов синхронно внутри create_pool() (до того,
    # как lifespan отдаёт управление uvicorn) — держим их прогретыми к первому запросу,
    # а не платим TCP+auth за коннект на холодном старте.
    postgres_pool_min_size: int = 4
    postgres_pool_max_size: int = 10

    def postgres_dsn(self, db: str | None = None) -> str:
        """DSN для asyncpg; db переопределяет имя БД (тестовая БД в фикстурах)."""
        dsn = (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{db or self.postgres_db}"
        )
        if self.postgres_sslmode:
            dsn += f"?sslmode={self.postgres_sslmode}"
        return dsn


__all__ = ["DbSettings"]
