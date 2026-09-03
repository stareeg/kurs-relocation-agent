"""Этап 4 (plans/vm_multitenant_hosting_2026_08_03.md §1): RLS реально режет чужие
строки на `resumes`, как и на таблицах воронки (см. tests/test_rls_pipeline_accounts.py — тот
же рецепт, та же идея, фундамент Этапа 1).

Маркер `db`, требует живой Postgres (см. test_rls_accounts.py — рецепт запуска).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import TimingPool, close_pool, get_pool, init_pool

pytestmark = pytest.mark.db

_ACCOUNT_A_TG_ID = 999_000_201
_ACCOUNT_B_TG_ID = 999_000_202
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


async def test_resumes_rls_hides_other_accounts_resume(db: TimingPool) -> None:
    """account_scope(B) не видит резюме аккаунта A даже без WHERE."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into resumes (account_id, data) values ($1, $2)",
            account_a,
            {"personal": {"full_name": "Аккаунт A"}},
        )

    async with account_scope(account_b) as scoped:
        assert await scoped.fetch("select account_id from resumes") == []

    async with account_scope(account_a) as scoped:
        own = await scoped.fetchrow("select data from resumes where account_id = $1", account_a)
        assert own["data"]["personal"]["full_name"] == "Аккаунт A"


async def test_resumes_upsert_is_one_row_per_account(db: TimingPool) -> None:
    """account_id — PK: повторное сохранение обновляет ту же строку, не плодит дубликаты."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into resumes (account_id, data) values ($1, $2) "
            "on conflict (account_id) do update set data = excluded.data",
            account_a,
            {"personal": {"full_name": "Версия 1"}},
        )
        await scoped.execute(
            "insert into resumes (account_id, data) values ($1, $2) "
            "on conflict (account_id) do update set data = excluded.data",
            account_a,
            {"personal": {"full_name": "Версия 2"}},
        )
        rows = await scoped.fetch("select data from resumes where account_id = $1", account_a)
        assert len(rows) == 1
        assert rows[0]["data"]["personal"]["full_name"] == "Версия 2"


async def test_app_admin_bypasses_rls_on_resumes(db: TimingPool) -> None:
    """app_admin (BYPASSRLS) видит резюме обоих аккаунтов — фоновые системные задачи."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into resumes (account_id, data) values ($1, $2)", account_a, {"x": "a"}
        )
    async with account_scope(account_b) as scoped:
        await scoped.execute(
            "insert into resumes (account_id, data) values ($1, $2)", account_b, {"x": "b"}
        )

    conn = await get_pool().acquire()
    try:
        await conn.execute("set role app_admin")
        rows = await conn.fetch(
            "select account_id from resumes where account_id = any($1::bigint[])",
            [account_a, account_b],
        )
        assert {r["account_id"] for r in rows} == {account_a, account_b}
    finally:
        await conn.execute("reset role")
        await get_pool().release(conn)
