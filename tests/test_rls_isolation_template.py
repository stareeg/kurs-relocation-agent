"""Самопроверка шаблона tests/rls_isolation.py (plans/multitenancy_gaps_2026_08_06.md §6):
доказывает, что `two_accounts` + `assert_isolated` реально работают, на уже готовой RLS-таблице
(`account_settings`) — прежде чем M1..M9 начнут полагаться на этот хелпер вместо копирования
boilerplate из tests/test_rls_accounts.py в каждый новый файл.

Маркер `db`, требует живой Postgres (см. tests/test_rls_accounts.py про запуск).
"""

from __future__ import annotations

import pytest

from tests.rls_isolation import assert_app_admin_bypasses, assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_account_settings_isolated_via_template(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into account_settings (account_id, key, value) "
            "values ($1, 'probe', '\"a\"'::jsonb)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select * from account_settings"),
    )


async def test_account_settings_app_admin_bypass_via_template(
    two_accounts: tuple[int, int],
) -> None:
    account_a, _account_b = two_accounts
    from core.platform.db.account_scope import account_scope

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into account_settings (account_id, key, value) "
            "values ($1, 'probe', '\"a\"'::jsonb)",
            account_a,
        )

    await assert_app_admin_bypasses(
        visible=lambda c: c.fetch(
            "select account_id from account_settings where account_id = $1", account_a
        )
    )
