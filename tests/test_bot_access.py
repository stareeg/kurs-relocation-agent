"""Этап 5 (plans/vm_multitenant_hosting_2026_08_03.md §5): «аккаунт» vs «оператор» в
`bot_app.access` — `resolve_account` (любой активный аккаунт) и `resolve_operator_account`
(оператор, привязывая env-admin'а на лету — TB-6.3, вынесено сюда из
`bot_app.services.auth_token`, покрыто тут напрямую).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import bot_app.access as access


@pytest.fixture(autouse=True)
def _reset_account_cache() -> None:
    """`resolve_account` кэширует по user_id (TTL 15с, ACCOUNT_CACHE_TTL_S) — без сброса
    между тестами один и тот же user_id в разных тестах читал бы чужой замоканный результат."""
    access.invalidate()
    yield
    access.invalidate()


@pytest.mark.asyncio
async def test_resolve_account_none_for_missing_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await access.resolve_account(user_id=None) is None


@pytest.mark.asyncio
async def test_resolve_account_none_when_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(_user_id: int, **_: Any) -> Any:
        return None

    monkeypatch.setattr(access, "get_account_by_telegram_user_id", fake_get)
    assert await access.resolve_account(user_id=123) is None


@pytest.mark.asyncio
async def test_resolve_account_none_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(_user_id: int, **_: Any) -> Any:
        return SimpleNamespace(status="disabled")

    monkeypatch.setattr(access, "get_account_by_telegram_user_id", fake_get)
    assert await access.resolve_account(user_id=123) is None


@pytest.mark.asyncio
async def test_resolve_account_returns_active_member_or_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = SimpleNamespace(status="active", role="member")

    async def fake_get(_user_id: int, **_: Any) -> Any:
        return account

    monkeypatch.setattr(access, "get_account_by_telegram_user_id", fake_get)
    assert await access.resolve_account(user_id=123) is account


@pytest.mark.asyncio
async def test_resolve_account_caches_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зовётся на каждый апдейт (account-context middleware, LLM key routing fix) — второй
    вызов для того же user_id в пределах TTL не должен бить в БД снова."""
    calls = {"n": 0}
    account = SimpleNamespace(status="active", role="member")

    async def fake_get(_user_id: int, **_: Any) -> Any:
        calls["n"] += 1
        return account

    monkeypatch.setattr(access, "get_account_by_telegram_user_id", fake_get)

    first = await access.resolve_account(user_id=123)
    second = await access.resolve_account(user_id=123)

    assert first is account
    assert second is account
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_resolve_operator_account_reuses_matching_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = SimpleNamespace(id=1, telegram_user_id=42)
    calls: dict[str, Any] = {"upserted": False}

    async def fake_resolve_owner(*, force: bool = False) -> Any:
        _ = force
        return owner

    async def fake_upsert_account(**_: Any) -> Any:
        calls["upserted"] = True
        raise AssertionError("не должно звать upsert_account — владелец уже совпадает")

    monkeypatch.setattr(access, "resolve_owner", fake_resolve_owner)
    monkeypatch.setattr(access, "upsert_account", fake_upsert_account)

    result = await access.resolve_operator_account(user_id=42, username="owner", chat_id=42)

    assert result is owner
    assert calls["upserted"] is False


@pytest.mark.asyncio
async def test_resolve_operator_account_links_env_admin_without_db_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TB-6.3: чистый env-allowlist доступ без DB-owner всё равно привязывается — иначе
    операторские пуши остаются заблокированы навсегда."""
    calls: dict[str, Any] = {}

    async def fake_resolve_owner(*, force: bool = False) -> Any:
        _ = force
        return None

    async def fake_upsert_account(
        *, telegram_user_id: int, telegram_username: Any, telegram_chat_id: Any, role: str
    ) -> Any:
        calls["kwargs"] = {
            "telegram_user_id": telegram_user_id,
            "telegram_username": telegram_username,
            "telegram_chat_id": telegram_chat_id,
            "role": role,
        }
        return SimpleNamespace(
            id=99,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            role=role,
        )

    invalidated = {"done": False}

    def fake_invalidate() -> None:
        invalidated["done"] = True

    monkeypatch.setattr(access, "resolve_owner", fake_resolve_owner)
    monkeypatch.setattr(access, "upsert_account", fake_upsert_account)
    monkeypatch.setattr(access, "invalidate", fake_invalidate)

    result = await access.resolve_operator_account(user_id=7, username="@Admin", chat_id=8)

    assert result.id == 99
    assert result.role == "owner"
    assert calls["kwargs"] == {
        "telegram_user_id": 7,
        "telegram_username": "Admin",
        "telegram_chat_id": 8,
        "role": "owner",
    }
    assert invalidated["done"] is True


@pytest.mark.asyncio
async def test_resolve_operator_account_relinks_when_different_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB-owner существует, но это не звонящий (второй env-admin) — привязка обновляется,
    не считается «уже совпадает»."""
    existing_owner = SimpleNamespace(id=1, telegram_user_id=1)

    async def fake_resolve_owner(*, force: bool = False) -> Any:
        _ = force
        return existing_owner

    async def fake_upsert_account(**kwargs: Any) -> Any:
        return SimpleNamespace(id=2, telegram_user_id=kwargs["telegram_user_id"], role="owner")

    monkeypatch.setattr(access, "resolve_owner", fake_resolve_owner)
    monkeypatch.setattr(access, "upsert_account", fake_upsert_account)
    monkeypatch.setattr(access, "invalidate", lambda: None)

    result = await access.resolve_operator_account(user_id=2, username="second-admin")

    assert result.telegram_user_id == 2
