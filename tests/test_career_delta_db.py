"""Сценарий `career_delta` — «Что изменилось» за 30 дней (Э9.5). Требует живой Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.app.scenarios.career_delta import career_delta
from core.domains.career.models import CareerFact, TimelineEvent
from core.domains.career.repo import insert_fact, insert_timeline_event
from core.platform.db.pool import get_pool
from tests.rls_isolation import two_accounts

pytestmark = pytest.mark.db


async def _insert_score(account_id: int, *, total: int, created_at: datetime) -> None:
    pool = get_pool()
    await pool.execute(
        "insert into resume_score_history "
        "(account_id, total, structure, market_coverage, writing, role_fit, created_at) "
        "values ($1, $2, $3, $4, $5, $6, $7)",
        account_id,
        total,
        total,
        total,
        total,
        total,
        created_at,
    )


async def test_none_with_single_snapshot(two_accounts) -> None:
    account_a, _account_b = two_accounts
    await _insert_score(account_a, total=70, created_at=datetime.now(UTC))
    assert await career_delta(account_id=account_a) is None


async def test_none_with_no_history_at_all(two_accounts) -> None:
    account_a, _account_b = two_accounts
    assert await career_delta(account_id=account_a) is None


async def test_resume_score_delta_with_two_snapshots(two_accounts) -> None:
    account_a, _account_b = two_accounts
    now = datetime.now(UTC)
    await _insert_score(account_a, total=70, created_at=now - timedelta(days=40))
    await _insert_score(account_a, total=86, created_at=now - timedelta(days=2))

    delta = await career_delta(account_id=account_a)

    assert delta is not None
    assert delta.resume_score_was == 70
    assert delta.resume_score_now == 86


async def test_new_facts_and_milestones_counted_only_inside_window(two_accounts) -> None:
    account_a, _account_b = two_accounts
    now = datetime.now(UTC)
    await _insert_score(account_a, total=70, created_at=now - timedelta(days=40))
    await _insert_score(account_a, total=86, created_at=now - timedelta(days=2))

    await insert_fact(
        CareerFact(fact="Старый факт", fact_type="note", source_kind="manual"),
        account_id=account_a,
    )  # recorded_at = now по умолчанию — внутри окна

    pool = get_pool()
    await pool.execute(
        "insert into career_facts (account_id, fact, fact_type, source_kind, recorded_at) "
        "values ($1, 'Факт до окна', 'note', 'manual', $2)",
        account_a,
        now - timedelta(days=45),
    )

    await insert_timeline_event(
        TimelineEvent(kind="other", title="Веха внутри окна"), account_id=account_a
    )
    await pool.execute(
        "insert into career_timeline (account_id, kind, title, occurred_at) "
        "values ($1, 'other', 'Веха до окна', $2)",
        account_a,
        now - timedelta(days=45),
    )

    delta = await career_delta(account_id=account_a)

    assert delta is not None
    assert delta.new_facts_count == 1
    assert delta.new_milestones_count == 1
