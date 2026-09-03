"""Этап 1 (plans/vm_multitenant_hosting_2026_08_03.md §1): RLS реально режет чужие строки.

Единственный тест в кодовой базе, который бьёт в живой Postgres (маркер `db`, по умолчанию
исключён — `addopts` в pyproject.toml). RLS нельзя замокать: политика — свойство самого
Postgres, а не Python-кода поверх него.

Перед прогоном нужен применённый 0095_accounts.sql:
    uv run python -m core.platform.db.migrate
    uv run pytest -m db tests/test_rls_accounts.py

Использует те же POSTGRES_* переменные, что и весь остальной рантайм (core.config), поэтому
локально бьёт в ту же БД, что и dev-запуск (uvicorn api.main:app), — тестовые аккаунты используют
заведомо не-телеграмные sentinel-id и удаляются в finally, чтобы не мусорить дев-базу при падении теста.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import TimingPool, close_pool, get_pool, init_pool

pytestmark = pytest.mark.db

# Telegram user_id реальных людей не бывает девятизначным с этим префиксом — безопасные sentinel.
_ACCOUNT_A_TG_ID = 999_000_001
_ACCOUNT_B_TG_ID = 999_000_002
_SENTINEL_TG_IDS = [_ACCOUNT_A_TG_ID, _ACCOUNT_B_TG_ID]


@pytest.fixture
async def db() -> AsyncIterator[TimingPool]:
    pool = await init_pool()
    try:
        yield pool
    finally:
        await pool.execute(
            "delete from accounts where telegram_user_id = any($1::bigint[])",
            _SENTINEL_TG_IDS,
        )
        await close_pool()


async def _make_account(pool: TimingPool, telegram_user_id: int) -> int:
    return await pool.fetchval(
        "insert into accounts (telegram_user_id, role) values ($1, 'member') returning id",
        telegram_user_id,
    )


async def test_account_scope_hides_other_accounts_rows(db: TimingPool) -> None:
    """account_scope(B) не видит ни строку accounts, ни account_settings аккаунта A."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into account_settings (account_id, key, value) "
            "values ($1, 'probe', '\"a\"'::jsonb)",
            account_a,
        )

    async with account_scope(account_b) as scoped:
        visible_settings = await scoped.fetch("select * from account_settings")
        assert visible_settings == []

        visible_accounts = await scoped.fetch("select id from accounts")
        assert [r["id"] for r in visible_accounts] == [account_b]


async def test_app_admin_role_bypasses_rls(db: TimingPool) -> None:
    """app_admin (BYPASSRLS) видит оба аккаунта независимо от app.account_id."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    conn = await db.acquire()
    try:
        await conn.execute("set role app_admin")
        rows = await conn.fetch(
            "select telegram_user_id from accounts where telegram_user_id = any($1::bigint[])",
            _SENTINEL_TG_IDS,
        )
        assert {r["telegram_user_id"] for r in rows} == {_ACCOUNT_A_TG_ID, _ACCOUNT_B_TG_ID}
    finally:
        await conn.execute("reset role")
        await db.release(conn)
