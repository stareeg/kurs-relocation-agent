"""Этап 3, домен 2 (plans/vm_multitenant_hosting_2026_08_03.md §1, §9, 0100_interview_stages_
account_id.sql): RLS реально режет чужие этапы собеседований на `interview_stages` — тот же
рецепт, что tests/test_rls_pipeline_accounts.py/tests/test_rls_resumes.py.

Маркер `db`, требует живой Postgres (см. test_rls_accounts.py — рецепт запуска).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import TimingPool, close_pool, get_pool, init_pool

pytestmark = pytest.mark.db

_ACCOUNT_A_TG_ID = 999_000_401
_ACCOUNT_B_TG_ID = 999_000_402
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


async def test_interview_stages_rls_hides_other_accounts_stages(db: TimingPool) -> None:
    """account_scope(B) не видит этап аккаунта A даже без WHERE — в т.ч. когда оба трекают
    одну и ту же публичную hh-вакансию (одинаковый vacancy_id, разные account_id)."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into interview_stages (account_id, vacancy_id, stage_type) "
            "values ($1, 'v-shared', 'hr_screening')",
            account_a,
        )
    async with account_scope(account_b) as scoped:
        await scoped.execute(
            "insert into interview_stages (account_id, vacancy_id, stage_type) "
            "values ($1, 'v-shared', 'hr_screening')",
            account_b,
        )

    async with account_scope(account_b) as scoped:
        rows = await scoped.fetch("select account_id from interview_stages")
        assert [r["account_id"] for r in rows] == [account_b]

    async with account_scope(account_a) as scoped:
        rows = await scoped.fetch("select account_id from interview_stages")
        assert [r["account_id"] for r in rows] == [account_a]


async def test_app_admin_bypasses_rls_on_interview_stages(db: TimingPool) -> None:
    """app_admin (BYPASSRLS) видит этапы обоих аккаунтов — фоновые системные задачи
    (digest cron, backfill-скрипты)."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into interview_stages (account_id, vacancy_id, stage_type) "
            "values ($1, 'v1', 'hr_screening')",
            account_a,
        )
    async with account_scope(account_b) as scoped:
        await scoped.execute(
            "insert into interview_stages (account_id, vacancy_id, stage_type) "
            "values ($1, 'v2', 'hr_screening')",
            account_b,
        )

    conn = await get_pool().acquire()
    try:
        await conn.execute("set role app_admin")
        rows = await conn.fetch(
            "select account_id from interview_stages where account_id = any($1::bigint[])",
            [account_a, account_b],
        )
        assert {r["account_id"] for r in rows} == {account_a, account_b}
    finally:
        await conn.execute("reset role")
        await get_pool().release(conn)
