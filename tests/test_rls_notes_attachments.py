"""RLS-изоляция M4 (plans/multitenancy_gaps_2026_08_06.md §3.4): заметки, вложения-
картинки, HR-guard-журнал. Живой Postgres, маркер `db` (`uv run pytest -m db ...`) — по образцу
`tests/rls_isolation.py` (общий хелпер M0)/`tests/test_rls_prep.py`, три строки на таблицу,
без ручного boilerplate `_make_account`/`db`-фикстуры.

`note_messages`/`hr_message_attachments` денормализуют `account_id` от родителя (`notes`/
`hr_messages`) — их родительскую строку заводим тем же `account_scope(account_a)`. `attachments`
(в отличие от M3, где она была SYSTEM без RLS) теперь тоже account-скоуп — unique(account_id,
sha256) вместо unique(sha256), см. 0105.
"""

from __future__ import annotations

import pytest

from core.platform.db.account_scope import account_scope
from tests.rls_isolation import assert_app_admin_bypasses, assert_isolated, two_accounts

pytestmark = pytest.mark.db


async def test_notes_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into notes (account_id, title, body) values ($1, 'заметка', 'текст')",
            account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from notes"),
    )


async def test_note_messages_isolated(two_accounts):
    account_a, account_b = two_accounts

    async def insert_as_a(c):
        note = await c.fetchrow(
            "insert into notes (account_id, title, body) values ($1, 'заметка', '') returning id",
            account_a,
        )
        await c.execute(
            "insert into note_messages (account_id, note_id, body) values ($1, $2, 'привет')",
            account_a, note["id"],
        )

    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=insert_as_a,
        visible_to_b=lambda c: c.fetch("select account_id from note_messages"),
    )


async def _insert_attachment(c, account_id: int) -> int:
    row = await c.fetchrow(
        "insert into attachments "
        "(account_id, sha256, mime, width, height, bytes, data, thumb, thumb_width, thumb_height) "
        "values ($1, $2, 'image/webp', 1, 1, 1, ''::bytea, ''::bytea, 1, 1) "
        "returning id",
        account_id, f"sha-rls-notes-test-{id(object())}",
    )
    assert row is not None
    return row["id"]


async def test_attachments_isolated(two_accounts):
    account_a, account_b = two_accounts

    async def insert_as_a(c):
        await _insert_attachment(c, account_a)

    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=insert_as_a,
        visible_to_b=lambda c: c.fetch("select account_id from attachments"),
    )


async def test_hr_message_attachments_isolated(two_accounts):
    account_a, account_b = two_accounts

    async def insert_as_a(c):
        attachment_id = await _insert_attachment(c, account_a)
        thread = await c.fetchrow(
            "insert into hr_threads (account_id, vacancy_id) values ($1, 'vac-1') returning id",
            account_a,
        )
        message = await c.fetchrow(
            "insert into hr_messages (account_id, thread_id) values ($1, $2) returning id",
            account_a, thread["id"],
        )
        await c.execute(
            "insert into hr_message_attachments (account_id, message_id, attachment_id) "
            "values ($1, $2, $3)",
            account_a, message["id"], attachment_id,
        )

    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=insert_as_a,
        visible_to_b=lambda c: c.fetch("select account_id from hr_message_attachments"),
    )


async def test_hr_forward_journal_isolated(two_accounts):
    account_a, account_b = two_accounts
    await assert_isolated(
        account_a=account_a,
        account_b=account_b,
        insert_as_a=lambda c: c.execute(
            "insert into hr_forward_journal (account_id, chat_id, text, scan) "
            "values ($1, $2, 'текст', '{}'::jsonb)",
            account_a, account_a,
        ),
        visible_to_b=lambda c: c.fetch("select account_id from hr_forward_journal"),
    )


async def test_app_admin_bypasses_notes_rls(two_accounts):
    """Системный путь (GC/бэкапы, план §1) обязан видеть строки всех аккаунтов."""
    account_a, _account_b = two_accounts
    async with account_scope(account_a) as scoped:
        await scoped.execute(
            "insert into notes (account_id, title, body) values ($1, 'admin-check', '')",
            account_a,
        )
    await assert_app_admin_bypasses(
        visible=lambda c: c.fetch(
            "select account_id from notes where title = 'admin-check'"
        )
    )
