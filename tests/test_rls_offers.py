"""M2 (plans/multitenancy_gaps_2026_08_06.md §3.2): кросс-аккаунтная изоляция офферов —
тот самый S1-баг («два аккаунта с оффером по одной вакансии пишут в одну строку»), теперь
проверенный на живой RLS.

Маркер `db`, требует живой Postgres (см. tests/test_rls_accounts.py про запуск:
`uv run pytest -m db ...`). Использует общий шаблон tests/rls_isolation.py — три строки
на таблицу, без копирования boilerplate.
"""

from __future__ import annotations

import pytest

from tests.rls_isolation import assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_offers_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into offers (account_id, vacancy_id, company) values ($1, 'v1', 'Acme')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select * from offers"),
    )


async def test_offer_comparisons_cache_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into offer_comparisons_cache (account_id, vacancy_ids_hash, comparison) "
            "values ($1, 'hash1', '{}'::jsonb)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select * from offer_comparisons_cache"),
    )
