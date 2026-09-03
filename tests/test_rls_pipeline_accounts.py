"""Этап 3, домен 1 (plans/vm_multitenant_hosting_2026_08_03.md §1): RLS реально режет
чужие строки на ретрофиченных таблицах воронки/HR-переписки, не только на accounts/
account_settings (см. tests/test_rls_accounts.py — та же идея, фундамент Этапа 1).

Маркер `db`, требует живой Postgres (см. test_rls_accounts.py — тот же рецепт запуска).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.platform.db.account_scope import account_scope
from core.platform.db.pool import TimingPool, close_pool, get_pool, init_pool

pytestmark = pytest.mark.db

_ACCOUNT_A_TG_ID = 999_000_101
_ACCOUNT_B_TG_ID = 999_000_102
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


async def test_jobs_rls_hides_other_accounts_vacancy(db: TimingPool) -> None:
    """account_scope(B) не видит jobs/application_stages аккаунта A даже без WHERE."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        job_id = await scoped.fetchval(
            "insert into jobs (account_id, vacancy_id, vacancy_text, status) "
            "values ($1, 'v-rls-1', 'текст вакансии', 'Просмотр') returning id",
            account_a,
        )
        await scoped.execute(
            "insert into application_stages (account_id, job_id, stage) values ($1, $2, 'Просмотр')",
            account_a,
            job_id,
        )

    async with account_scope(account_b) as scoped:
        visible_jobs = await scoped.fetch("select id from jobs where vacancy_id = 'v-rls-1'")
        assert visible_jobs == []
        visible_stages = await scoped.fetch(
            "select id from application_stages where job_id = $1", job_id
        )
        assert visible_stages == []

    # Тот же аккаунт снова видит свою строку — RLS не прячет собственные данные.
    async with account_scope(account_a) as scoped:
        own = await scoped.fetch("select id from jobs where vacancy_id = 'v-rls-1'")
        assert [r["id"] for r in own] == [job_id]


async def test_same_vacancy_id_two_accounts_do_not_collide(db: TimingPool) -> None:
    """Composite unique(account_id, vacancy_id) — два аккаунта трекают один HH-id независимо."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into jobs (account_id, vacancy_id, vacancy_text, status) "
            "values ($1, 'v-shared', 'текст A', 'Просмотр')",
            account_a,
        )
    async with account_scope(account_b) as scoped:
        await scoped.execute(
            "insert into jobs (account_id, vacancy_id, vacancy_text, status) "
            "values ($1, 'v-shared', 'текст B', 'Отклик')",
            account_b,
        )

    async with account_scope(account_a) as scoped:
        row = await scoped.fetchrow("select status from jobs where vacancy_id = 'v-shared'")
        assert row["status"] == "Просмотр"
    async with account_scope(account_b) as scoped:
        row = await scoped.fetchrow("select status from jobs where vacancy_id = 'v-shared'")
        assert row["status"] == "Отклик"


async def test_hr_threads_and_messages_rls_hides_other_account(db: TimingPool) -> None:
    """account_scope(B) не видит hr_threads/hr_messages аккаунта A."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        thread_id = await scoped.fetchval(
            "insert into hr_threads (account_id, vacancy_id) values ($1, 'v-hr-1') returning id",
            account_a,
        )
        await scoped.execute(
            "insert into hr_messages (account_id, thread_id, direction, body) "
            "values ($1, $2, 'in', 'привет от HR')",
            account_a,
            thread_id,
        )

    async with account_scope(account_b) as scoped:
        assert await scoped.fetch("select id from hr_threads where vacancy_id = 'v-hr-1'") == []
        assert (
            await scoped.fetch("select id from hr_messages where thread_id = $1", thread_id) == []
        )


async def test_app_admin_bypasses_rls_on_new_tables(db: TimingPool) -> None:
    """app_admin (BYPASSRLS) видит вакансии обоих аккаунтов — фоновые системные задачи."""
    account_a = await _make_account(db, _ACCOUNT_A_TG_ID)
    account_b = await _make_account(db, _ACCOUNT_B_TG_ID)

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into jobs (account_id, vacancy_id, vacancy_text, status) "
            "values ($1, 'v-admin-a', 'x', 'Просмотр')",
            account_a,
        )
    async with account_scope(account_b) as scoped:
        await scoped.execute(
            "insert into jobs (account_id, vacancy_id, vacancy_text, status) "
            "values ($1, 'v-admin-b', 'x', 'Просмотр')",
            account_b,
        )

    conn = await get_pool().acquire()
    try:
        await conn.execute("set role app_admin")
        rows = await conn.fetch(
            "select vacancy_id from jobs where vacancy_id = any($1::text[])",
            ["v-admin-a", "v-admin-b"],
        )
        assert {r["vacancy_id"] for r in rows} == {"v-admin-a", "v-admin-b"}
    finally:
        await conn.execute("reset role")
        await get_pool().release(conn)
