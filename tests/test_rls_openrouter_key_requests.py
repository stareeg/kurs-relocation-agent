"""Этап 5 (plans/vm_multitenant_hosting_2026_08_03.md §1): RLS реально режет чужие
заявки на `openrouter_key_requests`, как и на остальных account-скоуп таблицах (см.
tests/test_rls_resumes.py — тот же рецепт).

Маркер `db`, требует живой Postgres (см. test_rls_accounts.py — рецепт запуска).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import TimingPool, close_pool, get_pool, init_pool

pytestmark = pytest.mark.db

_ACCOUNT_A_TG_ID = 999_000_301
_ACCOUNT_B_TG_ID = 999_000_302
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


async def _make_account(pool: TimingPool, telegram_user_id: int, *, role: str = "member") -> int:
    return await pool.fetchval(
        "insert into accounts (telegram_user_id, role) values ($1, $2) returning id",
        telegram_user_id,
        role,
    )


async def test_key_requests_rls_hides_other_accounts_requests(db: TimingPool) -> None:
    """account_scope(B) не видит заявку аккаунта A даже без WHERE."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into openrouter_key_requests (account_id) values ($1)", account_a
        )

    async with account_scope(account_b) as scoped:
        assert await scoped.fetch("select id from openrouter_key_requests") == []

    async with account_scope(account_a) as scoped:
        own = await scoped.fetch(
            "select account_id, status from openrouter_key_requests where account_id = $1",
            account_a,
        )
        assert len(own) == 1
        assert own[0]["status"] == "pending"


async def test_app_admin_bypasses_rls_and_sees_all_pending(db: TimingPool) -> None:
    """app_admin (BYPASSRLS) видит заявки обоих аккаунтов — операторский путь (§4:
    сводка админ-панели читает openrouter_key_requests мимо account_scope)."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into openrouter_key_requests (account_id) values ($1)", account_a
        )
    async with account_scope(account_b) as scoped:
        await scoped.execute(
            "insert into openrouter_key_requests (account_id) values ($1)", account_b
        )

    conn = await get_pool().acquire()
    try:
        await conn.execute("set role app_admin")
        rows = await conn.fetch(
            "select account_id from openrouter_key_requests "
            "where account_id = any($1::bigint[]) and status = 'pending'",
            [account_a, account_b],
        )
        assert {r["account_id"] for r in rows} == {account_a, account_b}
    finally:
        await conn.execute("reset role")
        await get_pool().release(conn)


async def test_status_check_constraint_rejects_unknown_status(db: TimingPool) -> None:
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    import asyncpg

    async with account_scope(account_a) as scoped:
        with pytest.raises(asyncpg.CheckViolationError):
            await scoped.execute(
                "insert into openrouter_key_requests (account_id, status) values ($1, 'bogus')",
                account_a,
            )
