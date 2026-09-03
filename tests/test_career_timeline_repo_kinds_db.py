"""`list_timeline_events(kinds=..., before_id=...)` — фильтр по видам (Э9.3) и курсор «Показать
ещё» (Этап 2, plans/career_redesign_2026_08_26.md). Требует живой Postgres."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core.domains.career.models import TimelineEvent
from core.domains.career.repo import insert_timeline_event, list_timeline_events
from tests.rls_isolation import two_accounts

pytestmark = pytest.mark.db


async def test_kinds_filter_returns_only_matching_events(two_accounts) -> None:
    account_a, _account_b = two_accounts
    await insert_timeline_event(
        TimelineEvent(kind="job_start", title="Вышел на работу"), account_id=account_a
    )
    await insert_timeline_event(
        TimelineEvent(kind="certificate", title="Сертификат AWS"), account_id=account_a
    )
    await insert_timeline_event(TimelineEvent(kind="other", title="Прочее"), account_id=account_a)

    only_job_start = await list_timeline_events(account_id=account_a, kinds=["job_start"])
    assert [e.title for e in only_job_start] == ["Вышел на работу"]

    two_kinds = await list_timeline_events(account_id=account_a, kinds=["job_start", "certificate"])
    assert {e.kind for e in two_kinds} == {"job_start", "certificate"}

    unfiltered = await list_timeline_events(account_id=account_a)
    assert len(unfiltered) == 3


async def test_no_kinds_filter_returns_everything(two_accounts) -> None:
    account_a, _account_b = two_accounts
    await insert_timeline_event(
        TimelineEvent(kind="promotion", title="Повышение"), account_id=account_a
    )

    rows = await list_timeline_events(account_id=account_a, kinds=None)
    assert len(rows) == 1


async def test_before_id_cursor_continues_same_order(two_accounts) -> None:
    """Этап 2.4: курсор продолжает ровно тот же order by, что и первая страница."""
    account_a, _account_b = two_accounts
    base = datetime(2026, 8, 20, tzinfo=timezone.utc)
    for i in range(5):
        await insert_timeline_event(
            TimelineEvent(
                kind="other", title=f"Событие {i}", occurred_at=base + timedelta(hours=i)
            ),
            account_id=account_a,
        )

    first_page = await list_timeline_events(account_id=account_a, limit=2)
    assert [e.title for e in first_page] == ["Событие 4", "Событие 3"]

    second_page = await list_timeline_events(
        account_id=account_a, limit=2, before_id=first_page[-1].id
    )
    assert [e.title for e in second_page] == ["Событие 2", "Событие 1"]

    third_page = await list_timeline_events(
        account_id=account_a, limit=2, before_id=second_page[-1].id
    )
    assert [e.title for e in third_page] == ["Событие 0"]


async def test_duplicate_offer_publish_is_idempotent_on_real_db(two_accounts) -> None:
    """Этап 1, проверено и на реальном Postgres: partial unique index + on conflict работают."""
    account_a, _account_b = two_accounts
    evt = TimelineEvent(kind="offer", title="Оффер · Acme", source_ref="vac-real-1")

    first = await insert_timeline_event(evt, account_id=account_a)
    second = await insert_timeline_event(evt, account_id=account_a)

    assert first.id == second.id
    rows = await list_timeline_events(account_id=account_a, kinds=["offer"])
    assert len(rows) == 1
