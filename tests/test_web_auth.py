"""AUTH-1: долгоживущий web-токен из бота — ядро (`core.domains.profile.web_auth`).

Part C: токен — строка отдельной таблицы `account_sessions` (не колонки `accounts`) —
у аккаунта может быть несколько одновременно активных сессий (несколько устройств).
issue/revoke/find идут напрямую в SQL, не через `get_setting`/`set_setting`. Чистые функции
(хэш, переносимый токен) остаются plain unit-тестами; всё, что реально трогает
`accounts`/`account_sessions`, — `@pytest.mark.db` (маркер по аналогии с
`tests/test_rls_accounts.py`, требует применённой 0108_account_sessions.sql и живого
Postgres — `uv run pytest -m db tests/test_web_auth.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from core.domains.profile import web_auth as wa
from core.platform.db.pool import TimingPool, close_pool, init_pool
from core.platform.repo.accounts import (
    disable_account,
    get_owner_account,
    list_active_accounts,
    upsert_account,
)

# ---------- Чистые функции: без PG ----------


def test_generate_raw_token_is_urlsafe() -> None:
    token = wa.generate_raw_token()
    assert token
    assert all(c.isalnum() or c in "-_" for c in token)


def test_hash_token_is_stable_hex() -> None:
    assert wa.hash_token("abc") == wa.hash_token("abc")
    assert wa.hash_token("abc") != wa.hash_token("abd")
    assert len(wa.hash_token("abc")) == 64


def test_portable_token_roundtrip() -> None:
    token = wa.build_portable_token(user_id=42, username="@Friend")

    assert token.startswith(wa.PORTABLE_PREFIX)
    assert all(c.isalnum() or c in "-_." for c in token)
    parsed = wa.parse_portable_token(token)
    assert parsed is not None
    assert parsed.user_id == 42
    assert parsed.username == "Friend"  # без @

    # Без username — тоже валиден.
    anon = wa.parse_portable_token(wa.build_portable_token(user_id=7))
    assert anon is not None
    assert anon.user_id == 7
    assert anon.username is None


def test_parse_portable_rejects_garbage_and_plain_tokens() -> None:
    assert wa.parse_portable_token(None) is None
    assert wa.parse_portable_token("") is None
    assert wa.parse_portable_token("не токен вовсе") is None
    assert wa.parse_portable_token("cc.") is None
    assert wa.parse_portable_token("cc.abc") is None  # нет секрета
    assert wa.parse_portable_token("cc.%%%.secret") is None  # битый base64
    # Обычный токен владельца — не переносимый.
    assert wa.parse_portable_token(wa.generate_raw_token()) is None
    # user_id обязан быть положительным int.
    import base64 as b64

    def forged(payload: str) -> str:
        blob = b64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
        return f"cc.{blob}.secret"

    assert wa.parse_portable_token(forged('{"u":"нет"}')) is None
    assert wa.parse_portable_token(forged('{"u":0}')) is None
    assert wa.parse_portable_token(forged("[1,2]")) is None


# ---------- accounts-backed: требует живой Postgres (0096_accounts_identity.sql) ----------

_ACCOUNT_A_TG_ID = 999_100_001
_ACCOUNT_B_TG_ID = 999_100_002
_SENTINEL_TG_IDS = [_ACCOUNT_A_TG_ID, _ACCOUNT_B_TG_ID]


@pytest.fixture
async def db() -> AsyncIterator[TimingPool]:
    pool = await init_pool()
    try:
        yield pool
    finally:
        await pool.execute(
            "delete from accounts where telegram_user_id = any($1::bigint[])", _SENTINEL_TG_IDS
        )
        await close_pool()


@pytest.mark.db
async def test_issue_stores_only_sha256(db: TimingPool) -> None:
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID, telegram_username="Owner")
    issued = await wa.issue_web_auth_token(account.id)

    assert issued.token not in wa.hash_token(issued.token)
    sessions = await wa.list_sessions(account.id)
    assert len(sessions) == 1
    assert sessions[0].token_sha256 == wa.hash_token(issued.token)
    assert sessions[0].revoked_at is None


@pytest.mark.db
async def test_find_account_by_raw_token_matches_current_only(db: TimingPool) -> None:
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    issued = await wa.issue_web_auth_token(account.id)

    found = await wa.find_account_by_raw_token(issued.token)
    assert found is not None and found.id == account.id
    assert await wa.find_account_by_raw_token(issued.token + "x") is None
    assert await wa.find_account_by_raw_token("") is None
    assert await wa.find_account_by_raw_token(None) is None


@pytest.mark.db
async def test_reissue_keeps_both_tokens_active(db: TimingPool) -> None:
    """Part C: перевыпуск добавляет сессию, не заменяет — несколько устройств одновременно."""
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    first = await wa.issue_web_auth_token(account.id)
    second = await wa.issue_web_auth_token(account.id)

    assert first.account_id == second.account_id == account.id
    found_first = await wa.find_account_by_raw_token(first.token)
    found_second = await wa.find_account_by_raw_token(second.token)
    assert found_first is not None and found_first.id == account.id
    assert found_second is not None and found_second.id == account.id
    assert len(await wa.list_sessions(account.id)) == 2


@pytest.mark.db
async def test_revoke_session_by_token_blocks_only_that_session(db: TimingPool) -> None:
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    first = await wa.issue_web_auth_token(account.id)
    second = await wa.issue_web_auth_token(account.id)

    assert await wa.revoke_session_by_token(first.token) is True
    assert await wa.find_account_by_raw_token(first.token) is None
    found_second = await wa.find_account_by_raw_token(second.token)
    assert found_second is not None and found_second.id == account.id

    # Повторный отзыв той же сессии — no-op.
    assert await wa.revoke_session_by_token(first.token) is False


@pytest.mark.db
async def test_revoke_all_sessions_revokes_everything(db: TimingPool) -> None:
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    first = await wa.issue_web_auth_token(account.id)
    second = await wa.issue_web_auth_token(account.id)

    revoked = await wa.revoke_all_sessions(account.id)

    assert revoked == 2
    assert await wa.find_account_by_raw_token(first.token) is None
    assert await wa.find_account_by_raw_token(second.token) is None
    assert await wa.list_sessions(account.id) == []


@pytest.mark.db
async def test_reissue_after_revoke_reactivates(db: TimingPool) -> None:
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    old = await wa.issue_web_auth_token(account.id)
    await wa.revoke_session_by_token(old.token)

    issued = await wa.issue_web_auth_token(account.id)
    found = await wa.find_account_by_raw_token(issued.token)
    assert found is not None and found.id == account.id


@pytest.mark.db
async def test_any_web_auth_token_issued_reflects_ever_issued(db: TimingPool) -> None:
    was_ever_issued_before = await wa.any_web_auth_token_issued()
    account = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    issued = await wa.issue_web_auth_token(account.id)
    assert await wa.any_web_auth_token_issued() is True
    await wa.revoke_session_by_token(issued.token)
    # «Когда-либо выпущен» не откатывается отзывом — если и раньше было True, остаётся True.
    assert await wa.any_web_auth_token_issued() is True
    # Если раньше не было ни одной сессии — проверяем, что именно наш вызов создал «хоть раз».
    if not was_ever_issued_before:
        assert await wa.any_web_auth_token_issued() is True


@pytest.mark.db
async def test_list_active_sessions_with_accounts_excludes_revoked(db: TimingPool) -> None:
    a = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID)
    b = await upsert_account(telegram_user_id=_ACCOUNT_B_TG_ID)
    await wa.issue_web_auth_token(a.id)
    issued_b = await wa.issue_web_auth_token(b.id)
    await wa.revoke_session_by_token(issued_b.token)

    active = await wa.list_active_sessions_with_accounts()
    active_account_ids = {account.id for _session, account in active} & {a.id, b.id}
    assert active_account_ids == {a.id}


@pytest.mark.db
async def test_adopt_portable_binds_install(db: TimingPool) -> None:
    token = wa.build_portable_token(user_id=_ACCOUNT_A_TG_ID, username="friend")
    identity = wa.parse_portable_token(token)
    assert identity is not None

    account = await wa.adopt_portable_token(token, identity)

    assert account.telegram_user_id == _ACCOUNT_A_TG_ID
    assert account.telegram_username == "friend"
    found = await wa.find_account_by_raw_token(token)
    assert found is not None and found.id == account.id


@pytest.mark.db
async def test_adopt_portable_rotates_same_account(db: TimingPool) -> None:
    first_token = wa.build_portable_token(user_id=_ACCOUNT_A_TG_ID, username="friend")
    identity = wa.parse_portable_token(first_token)
    assert identity is not None
    first_account = await wa.adopt_portable_token(first_token, identity)

    second_token = wa.build_portable_token(user_id=_ACCOUNT_A_TG_ID, username="friend")
    second_account = await wa.adopt_portable_token(second_token, identity)

    assert second_account.id == first_account.id
    assert await wa.find_account_by_raw_token(first_token) is None
    found = await wa.find_account_by_raw_token(second_token)
    assert found is not None and found.id == first_account.id


@pytest.mark.db
async def test_get_owner_account_ignores_member_role(db: TimingPool) -> None:
    member = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID, role="member")
    owner = await get_owner_account()
    # Sentinel-id никогда не бывает реальным владельцем инсталляции — если get_owner_account()
    # вообще что-то вернул, это точно не свежесозданный member.
    assert owner is None or owner.id != member.id


@pytest.mark.db
async def test_list_active_accounts_excludes_disabled(db: TimingPool) -> None:
    """M8 (plans/multitenancy_gaps_2026_08_06.md §5.5): источник получателей для рассылок
    — активные аккаунты, disabled (отвязанные) не попадают в список."""
    active_member = await upsert_account(telegram_user_id=_ACCOUNT_A_TG_ID, role="member")
    disabled_member = await upsert_account(telegram_user_id=_ACCOUNT_B_TG_ID, role="member")
    await disable_account(disabled_member.id)

    ids = {a.id for a in await list_active_accounts()}

    assert active_member.id in ids
    assert disabled_member.id not in ids
