"""RLS-изоляция M3 (plans/multitenancy_gaps_2026_08_06.md §3.3): подготовка —
технички/скрининги/дебрифы/чат по вакансии/карта компетенций. Живой Postgres, маркер `db`
(`uv run pytest -m db ...`) — по образцу `tests/rls_isolation.py` (общий хелпер M0), три строки
на таблицу, без ручного boilerplate `_make_account`/`db`-фикстуры.

`debrief_attachments`/`prep_chat_message_attachments` денормализуют `account_id` от родителя
(`interview_debriefs`/`prep_chat_messages`) — их родительскую строку заводим тем же
`account_scope(account_a)`. `attachments` тоже account-скоуп с M4 (0105,
plans/multitenancy_gaps_2026_08_06.md §3.5) — строка заводится в том же `account_scope`, не
напрямую через `get_pool()`, как было до M4 (см. tests/test_rls_notes_attachments.py про саму
таблицу attachments).
"""

from __future__ import annotations

import pytest

from core.platform.db.account_scope import account_scope
from tests.rls_isolation import assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_prep_sessions_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into prep_sessions (account_id, vacancy_id) values ($1, $2)",
            account_a, "vac-1",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from prep_sessions"),
    )


async def test_prep_reminders_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into prep_reminders "
            "(account_id, vacancy_id, interview_dt, fire_at, chat_id) "
            "values ($1, $2, now(), now(), $3)",
            account_a, "vac-1", account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from prep_reminders"),
    )


async def test_prep_packs_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into prep_packs (account_id, vacancy_id, stage) values ($1, $2, $3)",
            account_a, "vac-1", "tech",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from prep_packs"),
    )


async def test_prep_topics_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into prep_topics (account_id, vacancy_id, stage, topic) "
            "values ($1, $2, $3, $4)",
            account_a, "vac-1", "tech", "RAG",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from prep_topics"),
    )


async def test_interview_debriefs_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into interview_debriefs (account_id, vacancy_id) values ($1, $2)",
            account_a, "vac-1",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from interview_debriefs"),
    )


async def test_vacancy_screening_questions_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into vacancy_screening_questions (account_id, vacancy_id) values ($1, $2)",
            account_a, "vac-1",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from vacancy_screening_questions"),
    )


async def test_prep_chat_messages_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into prep_chat_messages (account_id, vacancy_id, role, content) "
            "values ($1, $2, 'user', 'привет')",
            account_a, "vac-1",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from prep_chat_messages"),
    )


async def test_competency_ledger_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into competency_ledger (account_id, topic_canon, level, vacancy_id, stage) "
            "values ($1, 'RAG', 'weak', $2, 'tech')",
            account_a, "vac-1",
        ),
        visible_to_b=lambda c: c.fetch("select account_id from competency_ledger"),
    )


async def _insert_attachment(c, account_id: int) -> int:
    """`attachments` — account-скоуп с M4 (0105, plans/multitenancy_gaps_2026_08_06.md §3.5):
    строка заводится в том же `account_scope(account_a)`, что и связка (см.
    tests/test_rls_notes_attachments.py про саму таблицу attachments)."""
    row = await c.fetchrow(
        "insert into attachments "
        "(account_id, sha256, mime, width, height, bytes, data, thumb, thumb_width, thumb_height) "
        "values ($1, $2, 'image/webp', 1, 1, 1, ''::bytea, ''::bytea, 1, 1) "
        "returning id",
        account_id, f"sha-rls-test-{id(object())}",
    )
    assert row is not None
    return row["id"]


async def test_debrief_attachments_isolated(two_accounts):
    account_a, account_b = two_accounts

    async def insert_as_a(c):
        attachment_id = await _insert_attachment(c, account_a)
        debrief = await c.fetchrow(
            "insert into interview_debriefs (account_id, vacancy_id) values ($1, $2) "
            "returning id",
            account_a, "vac-1",
        )
        await c.execute(
            "insert into debrief_attachments (account_id, debrief_id, attachment_id) "
            "values ($1, $2, $3)",
            account_a, debrief["id"], attachment_id,
        )

    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=insert_as_a,
        visible_to_b=lambda c: c.fetch("select account_id from debrief_attachments"),
    )


async def test_prep_chat_message_attachments_isolated(two_accounts):
    account_a, account_b = two_accounts

    async def insert_as_a(c):
        attachment_id = await _insert_attachment(c, account_a)
        message = await c.fetchrow(
            "insert into prep_chat_messages (account_id, vacancy_id, role, content) "
            "values ($1, $2, 'user', 'скрин') returning id",
            account_a, "vac-1",
        )
        await c.execute(
            "insert into prep_chat_message_attachments (account_id, message_id, attachment_id) "
            "values ($1, $2, $3)",
            account_a, message["id"], attachment_id,
        )

    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=insert_as_a,
        visible_to_b=lambda c: c.fetch("select account_id from prep_chat_message_attachments"),
    )


async def test_app_admin_bypasses_prep_sessions_rls(two_accounts):
    """Системный путь (GC/бэкапы, план §1) обязан видеть строки всех аккаунтов."""
    from tests.rls_isolation import assert_app_admin_bypasses

    account_a, _account_b = two_accounts
    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into prep_sessions (account_id, vacancy_id) values ($1, $2)",
            account_a, "vac-admin-check",
        )
    await assert_app_admin_bypasses(
        visible=lambda c: c.fetch(
            "select account_id from prep_sessions where vacancy_id = 'vac-admin-check'"
        )
    )
