"""Маска «Администратор» и запрет auto-friend member↔member."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from api.security import AccountContext
from core.domains.career.friendships_repo import (
    ADMIN_DISPLAY_NAME,
    _enrich_friend_entry,
    friend_display,
    remove_friend,
)
from core.platform.repo.accounts import AccountRecord


def test_member_sees_owner_as_administrator() -> None:
    name, is_admin = friend_display(
        viewer_role="member", friend_role="owner", resume_name="Настоящее Имя"
    )
    assert name == ADMIN_DISPLAY_NAME
    assert is_admin is True


def test_owner_sees_member_resume_name() -> None:
    name, is_admin = friend_display(
        viewer_role="owner", friend_role="member", resume_name="Друг"
    )
    assert name == "Друг"
    assert is_admin is False


def test_member_member_keeps_resume_name() -> None:
    name, is_admin = friend_display(
        viewer_role="member", friend_role="member", resume_name="Коллега"
    )
    assert name == "Коллега"
    assert is_admin is False


def test_empty_resume_name_not_leaked_as_owner_nick() -> None:
    name, is_admin = friend_display(viewer_role="member", friend_role="owner", resume_name="")
    assert name == ADMIN_DISPLAY_NAME
    assert is_admin is True


def _account(*, account_id: int, role: str, username: str) -> AccountRecord:
    return AccountRecord(
        id=account_id,
        telegram_user_id=account_id * 10,
        telegram_username=username,
        telegram_chat_id=account_id * 100,
        role=role,  # type: ignore[arg-type]
        status="active",
    )


class _FakeDb:
    def __init__(self, *, origin: str = "system_admin", full_name: str = "Секретное Имя") -> None:
        self.origin = origin
        self.full_name = full_name
        self.deleted = False

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        _ = args
        if "select origin" in sql:
            return {"origin": self.origin}
        if "full_name" in sql:
            return {"full_name": self.full_name}
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        _ = sql, args
        self.deleted = True
        return "DELETE 1"


@pytest.mark.asyncio
async def test_list_enrich_masks_owner_name(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.domains.career.friendships_repo as repo

    async def fake_get(account_id: int, *, db: Any = None) -> AccountRecord:
        _ = db
        if account_id == 1:
            return _account(account_id=1, role="member", username="friend")
        return _account(account_id=2, role="owner", username="stareeg")

    monkeypatch.setattr(repo, "get_account_by_id", fake_get)
    entry = await _enrich_friend_entry(
        {
            "id": 9,
            "account_id": 1,
            "friend_account_id": 2,
            "status": "active",
            "origin": "system_admin",
            "created_at": None,
        },
        viewer_account_id=1,
        db=_FakeDb(),
    )
    assert entry.friend_name == ADMIN_DISPLAY_NAME
    assert entry.is_admin_peer is True
    assert entry.friend_email == ""
    assert "stareeg" not in entry.friend_name


@pytest.mark.asyncio
async def test_remove_system_admin_edge_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.domains.career.friendships_repo as repo

    async def fake_get(account_id: int, *, db: Any = None) -> AccountRecord:
        _ = db
        if account_id == 1:
            return _account(account_id=1, role="member", username="friend")
        return _account(account_id=2, role="owner", username="op")

    monkeypatch.setattr(repo, "get_account_by_id", fake_get)
    db = _FakeDb(origin="system_admin")
    assert await remove_friend(2, account_id=1, db=db) == "forbidden"
    assert db.deleted is False


@pytest.mark.asyncio
async def test_remove_user_origin_owner_peer_still_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Маска по роли: даже origin=user на owner нельзя снести member'у."""
    import core.domains.career.friendships_repo as repo

    async def fake_get(account_id: int, *, db: Any = None) -> AccountRecord:
        _ = db
        if account_id == 1:
            return _account(account_id=1, role="member", username="friend")
        return _account(account_id=2, role="owner", username="op")

    monkeypatch.setattr(repo, "get_account_by_id", fake_get)
    db = _FakeDb(origin="user")
    assert await remove_friend(2, account_id=1, db=db) == "forbidden"
    assert db.deleted is False


@pytest.mark.asyncio
async def test_friends_remove_router_maps_forbidden_to_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.routers.career import friendships as friendships_router

    async def fake_remove(friend_account_id: int, *, account_id: int) -> str:
        _ = friend_account_id, account_id
        return "forbidden"

    monkeypatch.setattr(friendships_router, "remove_friend", fake_remove)
    member = AccountContext(
        account_id=1, telegram_user_id=10, telegram_username="friend", role="member"
    )
    with pytest.raises(HTTPException) as exc:
        await friendships_router.friends_remove(2, account=member)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_repair_pass_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ремонт дружб — подстраховка, а не часть чтения витрины.

    Раньше проход по всем активным member шёл на каждый опрос `/api/admin/overview`
    (дважды в минуту на вкладку). Троттлинг допускает один проход в 10 минут на процесс.
    """
    import core.domains.career.friendships_repo as repo

    repo.reset_friendship_repair_throttle()
    calls = 0

    async def fake_repair(*, db: Any = None) -> None:
        nonlocal calls
        _ = db
        calls += 1

    monkeypatch.setattr(repo, "ensure_all_system_admin_friendships", fake_repair)

    assert await repo.ensure_all_system_admin_friendships_throttled() is True
    assert await repo.ensure_all_system_admin_friendships_throttled() is False
    assert await repo.ensure_all_system_admin_friendships_throttled() is False
    assert calls == 1

    # Окно истекло — проход снова разрешён.
    monkeypatch.setattr(repo.time, "monotonic", lambda: 10_000_000.0)
    assert await repo.ensure_all_system_admin_friendships_throttled() is True
    assert calls == 2

    repo.reset_friendship_repair_throttle()

