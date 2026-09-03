"""RLS-изоляция M5 (plans/multitenancy_gaps_2026_08_06.md §3.6): рынок, режим поиска,
career, калибровка зарплат. Живой Postgres, маркер `db` (`uv run pytest -m db ...`) — по образцу
`tests/rls_isolation.py` (общий хелпер M0), три строки на таблицу, без ручного boilerplate.

Де-факто изолированные по `chat_id` таблицы (`tg_ui_messages`, `salary_calibration_queue`,
`salary_calibration_sessions`) тоже проверяются здесь — `account_id` теперь есть и на них
(единообразие/будущий RLS, план §2), поведение RLS должно совпадать с остальными.
"""

from __future__ import annotations

import pytest

from core.platform.db.account_scope import account_scope
from tests.rls_isolation import assert_app_admin_bypasses, assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_search_state_log_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into search_state_log (account_id, mode) values ($1, 'active')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from search_state_log"),
    )


async def test_situation_narratives_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into situation_narratives (account_id, summary) values ($1, 'сводка')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from situation_narratives"),
    )


async def test_market_analytics_snapshot_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into market_analytics_snapshot (account_id, kind) values ($1, 'grid')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from market_analytics_snapshot"),
    )


async def test_market_snapshots_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into market_snapshots (account_id, day) values ($1, current_date)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from market_snapshots"),
    )


async def test_discovery_presets_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into discovery_presets (account_id, name, url) "
            "values ($1, 'llm-msk', 'https://hh.ru/search/vacancy?text=llm')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from discovery_presets"),
    )


async def test_tg_ui_messages_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into tg_ui_messages (account_id, chat_id, message_id, kind) "
            "values ($1, $1, 1, 'menu')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from tg_ui_messages"),
    )


async def test_salary_calibration_queue_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into salary_calibration_queue (account_id, chat_id, message_id, raw_text) "
            "values ($1, $1, 1, 'вилка 300-400к')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from salary_calibration_queue"),
    )


async def test_salary_calibration_sessions_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into salary_calibration_sessions (account_id, chat_id) values ($1, $1)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from salary_calibration_sessions"),
    )


async def test_salary_calibration_samples_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into salary_calibration_samples (account_id) values ($1)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from salary_calibration_samples"),
    )


async def test_salary_calibration_meta_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into salary_calibration_meta (account_id, key, value) values ($1, 'k', 'v')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from salary_calibration_meta"),
    )


async def test_career_timeline_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into career_timeline (account_id, kind, title) values ($1, 'other', 'Веха')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from career_timeline"),
    )


async def test_career_portfolio_items_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into career_portfolio_items (account_id, project) values ($1, 'Проект X')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from career_portfolio_items"),
    )


async def test_career_facts_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into career_facts (account_id, fact, source_kind) "
            "values ($1, 'Подтянуть: RAG eval', 'debrief')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from career_facts"),
    )


async def test_app_admin_bypasses_market_career_rls(two_accounts):
    """Системный путь (маркет-агрегация/GC, план §1) обязан видеть строки всех аккаунтов."""
    account_a, _account_b = two_accounts
    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into career_timeline (account_id, kind, title) values ($1, 'other', "
            "'admin-check')",
            account_a,
        )
    await assert_app_admin_bypasses(
        visible=lambda c: c.fetch(
            "select account_id from career_timeline where title = 'admin-check'"
        )
    )
