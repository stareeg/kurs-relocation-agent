"""M6 (plans/multitenancy_gaps_2026_08_06.md §3.8): кросс-аккаунтная изоляция
llm_usage/background_tasks — в отличие от M1-M5 обе таблицы допускают NULL account_id
(строки без личного владельца: system-кайнды очереди, LLM-вызовы вне request/task-контекста),
поэтому кроме общего `assert_isolated` здесь есть свой тест на видимость NULL-строк.

Маркер `db`, требует живой Postgres (см. tests/test_rls_accounts.py про запуск:
`uv run pytest -m db ...`).
"""

from __future__ import annotations

import pytest

from core.platform.db.account_scope import account_scope
from tests.rls_isolation import assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_llm_usage_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into llm_usage (agent, model, tokens_in, tokens_out, cost_usd, account_id) "
            "values ('agent', 'model', 1, 1, 0.001, $1)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select * from llm_usage"),
    )


async def test_background_tasks_account_row_isolated(two_accounts: tuple[int, int]) -> None:
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into background_tasks (kind, payload, account_id) "
            "values ('salary_estimate', '{}'::jsonb, $1)",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch(
            "select * from background_tasks where account_id is not null"
        ),
    )


async def test_background_tasks_system_row_visible_to_everyone(
    two_accounts: tuple[int, int],
) -> None:
    """account_id IS NULL — системный kind (GC/маркет-агрегация/cron-уборка), не персональные
    данные (рисков) — видны под любым account_id, не только тому, кто их создал.

    Ключ-маркер в idempotency_key, а не голый `kind = 'attachments_gc'` — эта dev-БД живая
    (реальный воркер уже кладёт настоящие GC-задачи), голый фильтр по kind считал бы их тоже.
    """
    account_a, account_b = two_accounts
    marker = f"test_rls_platform_marker:{account_a}:{account_b}"

    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into background_tasks (kind, payload, idempotency_key) "
            "values ('attachments_gc', '{}'::jsonb, $1)",
            marker,
        )

    try:
        async with account_scope(account_b) as scoped:
            rows = await scoped.fetch(
                "select * from background_tasks where idempotency_key = $1", marker
            )
            assert len(rows) == 1, (
                "системная задача (account_id is null) должна быть видна B тоже"
            )
    finally:
        # account_id is null не каскадится при удалении test-аккаунтов (two_accounts fixture) —
        # без явной уборки маркерная строка осталась бы мусором в общей dev-БД навсегда.
        async with account_scope(account_a) as scoped:
            await scoped.execute(
                "delete from background_tasks where idempotency_key = $1", marker
            )
