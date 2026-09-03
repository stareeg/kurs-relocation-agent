"""«Добавить аккаунт» — привязка ещё одного Telegram-id к существующему аккаунту
(`bot_app.services.account_link`), без Telegram-моков (как `tests/test_bot_auth_token.py`).
"""

from __future__ import annotations

from typing import Any

import pytest

import bot_app.access as access
import bot_app.services.account_link as svc
from tests.fake_accounts import FakeAccountsStore


@pytest.fixture
def store() -> FakeAccountsStore:
    return FakeAccountsStore()


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, store: FakeAccountsStore) -> dict[str, Any]:
    state: dict[str, Any] = {"invalidated": False, "current_by_user": {}}

    async def fake_resolve_account(*, user_id: int) -> Any:
        return state["current_by_user"].get(user_id)

    def fake_invalidate() -> None:
        state["invalidated"] = True

    monkeypatch.setattr(access, "resolve_account", fake_resolve_account)
    monkeypatch.setattr(access, "invalidate", fake_invalidate)
    store.patch_account_link_module(monkeypatch, svc)
    return state


async def _account(store: FakeAccountsStore, *, telegram_user_id: int, role: str = "owner") -> Any:
    return await store.upsert_account(telegram_user_id=telegram_user_id, role=role)


@pytest.mark.asyncio
async def test_token_not_found(env: dict[str, Any]) -> None:
    outcome = await svc.link_telegram_account(
        raw_token="garbage", user_id=1, chat_id=1, username=None
    )
    assert outcome.ok is False
    assert outcome.reason == "not_found"


@pytest.mark.asyncio
async def test_clean_link_from_scratch(env: dict[str, Any], store: FakeAccountsStore) -> None:
    """Гость (без своего аккаунта) присылает чужой токен — привязывается как secondary,
    новый accounts-ряд не заводится."""
    target = await _account(store, telegram_user_id=100, role="owner")
    issued = await store.issue_web_auth_token(target.id)

    outcome = await svc.link_telegram_account(
        raw_token=issued.token, user_id=200, chat_id=200, username="second"
    )

    assert outcome.ok is True
    assert outcome.account is not None and outcome.account.id == target.id
    assert store._links[200] == target.id
    assert env["invalidated"] is True
    # Ни одного лишнего accounts-ряда не появилось.
    assert len(store._rows) == 1


@pytest.mark.asyncio
async def test_already_linked_is_a_noop(env: dict[str, Any], store: FakeAccountsStore) -> None:
    target = await _account(store, telegram_user_id=100, role="owner")
    issued = await store.issue_web_auth_token(target.id)
    env["current_by_user"][200] = target

    outcome = await svc.link_telegram_account(
        raw_token=issued.token, user_id=200, chat_id=200, username="second"
    )

    assert outcome.ok is False
    assert outcome.reason == "already_linked"
    assert 200 not in store._links


@pytest.mark.asyncio
async def test_empty_duplicate_is_silently_disabled_and_merged(
    env: dict[str, Any], store: FakeAccountsStore
) -> None:
    target = await _account(store, telegram_user_id=100, role="owner")
    issued = await store.issue_web_auth_token(target.id)
    duplicate = await _account(store, telegram_user_id=200, role="member")
    env["current_by_user"][200] = duplicate
    store.set_content(duplicate.id, False)

    outcome = await svc.link_telegram_account(
        raw_token=issued.token, user_id=200, chat_id=200, username="second"
    )

    assert outcome.ok is True
    assert outcome.account is not None and outcome.account.id == target.id
    assert store._rows[duplicate.id]["status"] == "disabled"
    assert store._links[200] == target.id


@pytest.mark.asyncio
async def test_nonempty_duplicate_is_refused(
    env: dict[str, Any], store: FakeAccountsStore
) -> None:
    target = await _account(store, telegram_user_id=100, role="owner")
    issued = await store.issue_web_auth_token(target.id)
    duplicate = await _account(store, telegram_user_id=200, role="member")
    env["current_by_user"][200] = duplicate
    store.set_content(duplicate.id, True)

    outcome = await svc.link_telegram_account(
        raw_token=issued.token, user_id=200, chat_id=200, username="second"
    )

    assert outcome.ok is False
    assert outcome.reason == "conflict"
    assert outcome.account is not None and outcome.account.id == duplicate.id
    # Ничего не тронуто: дубль жив, линк не появился.
    assert store._rows[duplicate.id]["status"] == "active"
    assert 200 not in store._links
