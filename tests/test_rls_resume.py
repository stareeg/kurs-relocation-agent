"""M1 (plans/multitenancy_gaps_2026_08_06.md §3.1): кросс-аккаунтная изоляция резюме-
скора и его производных — тот самый S1-баг («резюме друга стало резюме для всех»), теперь
проверенный на живой RLS, не только на уровне Python-кэша (и правка
core/domains/profile/structured_store.py в этом же этапе).

Маркер `db`, требует живой Postgres (см. tests/test_rls_accounts.py про запуск:
`uv run pytest -m db ...`). Использует общий шаблон tests/rls_isolation.py — три строки
на таблицу, без копирования boilerplate.
"""

from __future__ import annotations

import pytest

from tests.rls_isolation import assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_resume_score_history_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into resume_score_history (account_id, total, structure, writing, role_fit) "
            "values ($1, 50, 50, 50, 50)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select * from resume_score_history"),
    )


async def test_resume_stats_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into resume_stats (account_id) values ($1)", account_a
        ),
        visible_to_b=lambda c: c.fetch("select * from resume_stats"),
    )


async def test_resume_views_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into resume_views (account_id) values ($1)", account_a
        ),
        visible_to_b=lambda c: c.fetch("select * from resume_views"),
    )


async def test_gm_profile_snapshots_isolated(two_accounts: tuple[int, int]) -> None:
    """GM-13: снимки getmatch-профиля account-scoped — друг не видит профиль владельца."""
    from core.platform.db.pool import table_exists

    if not await table_exists("gm_profile_snapshots"):
        pytest.skip("таблица gm_profile_snapshots не создана (миграция 0125)")
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into gm_profile_snapshots (account_id) values ($1)", account_a
        ),
        visible_to_b=lambda c: c.fetch("select * from gm_profile_snapshots"),
    )


async def test_gm_trust_snapshots_isolated(two_accounts: tuple[int, int]) -> None:
    """GM-12: снимки чеклиста доверия getmatch account-scoped — друг не видит чужой статус."""
    from core.platform.db.pool import table_exists

    if not await table_exists("gm_trust_snapshots"):
        pytest.skip("таблица gm_trust_snapshots не создана (миграция 0126)")
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into gm_trust_snapshots (account_id) values ($1)", account_a
        ),
        visible_to_b=lambda c: c.fetch("select * from gm_trust_snapshots"),
    )


async def test_resume_skill_snapshots_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into resume_skill_snapshots (account_id) values ($1)", account_a
        ),
        visible_to_b=lambda c: c.fetch("select * from resume_skill_snapshots"),
    )


async def test_resume_skill_suggestions_isolated(two_accounts: tuple[int, int]) -> None:
    """Строки денормализуют account_id от снимка (тот же приём, что hr_messages от hr_threads
    в 0097) — вставка идёт в обе таблицы под одним account_scope."""
    account_a, account_b = two_accounts

    async def _insert_snapshot_and_suggestion(c) -> None:
        snapshot = await c.fetchrow(
            "insert into resume_skill_snapshots (account_id) values ($1) returning id",
            account_a,
        )
        await c.execute(
            "insert into resume_skill_suggestions (account_id, snapshot_id, skill, state) "
            "values ($1, $2, 'Python', 'have')",
            account_a,
            snapshot["id"],
        )

    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=_insert_snapshot_and_suggestion,
        visible_to_b=lambda c: c.fetch("select * from resume_skill_suggestions"),
    )
