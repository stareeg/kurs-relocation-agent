"""Гейт админ-консоли: только role=owner, анонимный /auth/status без is_admin."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.security import AccountContext, require_platform_admin
from core.platform.admin.models import AdminError
from core.platform.admin.service import disable_user, enable_user
from tests.fake_accounts import FakeAccountsStore


def _ctx(*, account_id: int, role: str, username: str = "u") -> AccountContext:
    return AccountContext(
        account_id=account_id,
        telegram_user_id=account_id * 10,
        telegram_username=username,
        role=role,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_require_platform_admin_rejects_member() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_platform_admin(account=_ctx(account_id=2, role="member"))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_platform_admin_allows_owner() -> None:
    owner = _ctx(account_id=1, role="owner", username="op")
    assert await require_platform_admin(account=owner) is owner


@pytest.mark.asyncio
async def test_disable_self_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    store.patch_accounts_module(
        monkeypatch, __import__("core.platform.admin.service", fromlist=["x"])
    )
    with pytest.raises(AdminError) as exc:
        await disable_user(owner.id, actor_id=owner.id)
    assert "свой" in str(exc.value.message)


@pytest.mark.asyncio
async def test_disable_member_and_enable(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    member = await store.upsert_account(
        telegram_user_id=2, telegram_username="friend", role="member"
    )
    import core.platform.admin.service as admin_svc

    store.patch_accounts_module(monkeypatch, admin_svc)

    async def fake_revoke(account_id: int) -> int:
        _ = account_id
        return 2

    monkeypatch.setattr(admin_svc, "_revoke_sessions", fake_revoke)
    await disable_user(member.id, actor_id=owner.id)
    row = await store.get_account_by_id(member.id)
    assert row is not None
    assert row.status == "disabled"
    await enable_user(member.id, actor_id=owner.id)
    row = await store.get_account_by_id(member.id)
    assert row is not None
    assert row.status == "active"


@pytest.mark.asyncio
async def test_disable_owner_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    other = await store.upsert_account(telegram_user_id=9, telegram_username="x", role="member")
    import core.platform.admin.service as admin_svc

    store.patch_accounts_module(monkeypatch, admin_svc)
    with pytest.raises(AdminError):
        await disable_user(owner.id, actor_id=other.id)


@pytest.mark.asyncio
async def test_disable_member_sessions_stop_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """status=disabled + отзыв сессий: старый токен не пускает, новый после enable — пускает."""
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    member = await store.upsert_account(
        telegram_user_id=2, telegram_username="friend", role="member"
    )
    issued = await store.issue_web_auth_token(member.id)
    import core.platform.admin.service as admin_svc

    store.patch_accounts_module(monkeypatch, admin_svc)

    async def fake_revoke(account_id: int) -> int:
        return await store.revoke_all_sessions(account_id)

    monkeypatch.setattr(admin_svc, "_revoke_sessions", fake_revoke)
    assert await store.find_account_by_raw_token(issued.token) is not None
    await disable_user(member.id, actor_id=owner.id)
    assert await store.find_account_by_raw_token(issued.token) is None
    await enable_user(member.id, actor_id=owner.id)
    assert await store.find_account_by_raw_token(issued.token) is None
    fresh = await store.issue_web_auth_token(member.id)
    found = await store.find_account_by_raw_token(fresh.token)
    assert found is not None
    assert found.id == member.id


@pytest.mark.asyncio
async def test_load_summary_empty_without_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.platform.admin.service as admin_svc
    from core.platform.admin.service import load_summary

    async def fake_fetch(sql: str, *args: object, **kwargs: object) -> list:
        _ = sql, args, kwargs
        return []

    async def fake_fetchrow(sql: str, *args: object, **kwargs: object) -> None:
        _ = sql, args, kwargs
        return None

    monkeypatch.setattr(admin_svc, "_fetch", fake_fetch)
    monkeypatch.setattr(admin_svc, "_fetchrow", fake_fetchrow)
    monkeypatch.setattr(admin_svc, "migration_numbers", lambda: [1])
    summary = await load_summary()
    assert summary.accounts_active == 0
    assert summary.pending_keys == 0
    # Пустой ответ без исключений — это «данных нет», а не «витрина сломалась».
    assert summary.degraded is False
    assert summary.health.postgres_ok is False
