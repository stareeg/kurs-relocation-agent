"""E-9 в Postgres: расход в строке запуска и `llm_usage.agent_run_id` для сверки.

Маркер `db`, требует живой Postgres с миграциями (`python -m core.platform.db.migrate`).
"""

from __future__ import annotations

import asyncio

import pytest

from core.platform.config.runtime import (
    reset_current_account_id,
    reset_current_agent_run_id,
    set_current_account_id,
    set_current_agent_run_id,
)
from core.platform.db.pool import get_pool
from core.platform.repo import agent_runs as runs_repo
from core.platform.repo.usage import PostgresUsageSink
from tests.rls_isolation import two_accounts  # noqa: F401 — фикстура pytest

pytestmark = pytest.mark.db


async def test_run_usage_roundtrip_and_llm_usage_attribution(
    two_accounts: tuple[int, int],  # noqa: F811 — фикстура
) -> None:
    account_a, _ = two_accounts
    run = await runs_repo.create_run(account_id=account_a, goal="e9", thread_id="e9-db-test")
    assert run.usage == {}

    usage = {
        "model_calls": 2,
        "tokens_in": 1500,
        "tokens_out": 90,
        "cost_usd": 0.00042,
        "cost_self_hosted_usd": 0.0,
        "by_group": {"judge": {"calls": 1, "tokens_in": 900, "tokens_out": 60, "cost_usd": 0.00042}},
    }
    updated = await runs_repo.update_run(
        run.id, account_id=account_a, status="done", usage=usage
    )
    assert updated is not None and updated.usage == usage
    again = await runs_repo.get_run(run.id, account_id=account_a)
    assert again is not None and again.usage["by_group"]["judge"]["tokens_in"] == 900

    pool = get_pool()
    sink = PostgresUsageSink(pool)
    account_token = set_current_account_id(account_a)
    run_token = set_current_agent_run_id(run.id)
    try:
        sink.record("agent_step", "glm-5.3-flash", 600, 30, 0.0)
        sink.record("agent_judge_step", "openrouter-reserve", 900, 60, 0.00042)
    finally:
        reset_current_agent_run_id(run_token)
        reset_current_account_id(account_token)
    sink.record("job_search", "glm-5.3-flash", 50, 5, 0.0)  # вне запуска — без agent_run_id
    await asyncio.gather(*list(sink._tasks))

    try:
        row = await pool.fetchrow(
            "select count(*)::int calls, sum(tokens_in)::int tin, sum(tokens_out)::int tout"
            " from llm_usage where agent_run_id = $1",
            run.id,
        )
        assert (row["calls"], row["tin"], row["tout"]) == (2, 1500, 90)
    finally:
        await pool.execute(
            "delete from llm_usage where agent_run_id = $1"
            " or (agent = 'job_search' and tokens_in = 50 and tokens_out = 5 and account_id is null"
            " and ts > now() - interval '5 minutes')",
            run.id,
        )
