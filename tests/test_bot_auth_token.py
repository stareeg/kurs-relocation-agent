"""AUTH-1 / Этап 5: кнопка «Токен авторизации» в боте (`bot_app.services.auth_token`).

Сценарии: оператор получает/перевыпускает токен; любой другой Telegram-пользователь —
self-serve MEMBER-аккаунт на этой же инсталляции (план §5) — раньше это была выдача
переносимого токена для чужой отдельной установки, с общим хостингом это больше не нужно.
Владельцем становится ТОЛЬКО совпадение с env-allowlist — bootstrap «первый нажавший
становится владельцем» убран: единый продуктовый бот всегда деплоится с заранее известным
`ADMIN_USER_ID`/`ADMIN_USER_IDS`.

Этап 5 вынес привязку env-admin'а из этого модуля в
`bot_app.access.resolve_operator_account` — здесь она мокается напрямую, поведенческие тесты
самой привязки — `tests/test_bot_access.py`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import bot_app.access as access
from bot_app.services import auth_token as svc


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Мокнутые зависимости: access-флаги, resolve_operator_account, upsert/issue токена."""
    state: dict[str, Any] = {
        "allowed": False,
        "operator_account": None,
        "invalidated": False,
        "issued_for": None,
        "upserted": None,
        "last_issued_at": None,
        "web_login_done": True,
    }

    async def fake_is_allowed_admin(*, user_id: int | None, username: str | None, **_: Any) -> bool:
        _ = user_id, username
        return bool(state["allowed"])

    def fake_invalidate() -> None:
        state["invalidated"] = True

    async def fake_resolve_operator_account(
        *, user_id: int, username: str | None, chat_id: int | None = None
    ) -> Any:
        _ = user_id, username, chat_id
        account = state["operator_account"]
        assert account is not None, "тест должен задать env['operator_account']"
        return account

    async def fake_upsert_account(
        *,
        telegram_user_id: int,
        telegram_username: str | None = None,
        telegram_chat_id: int | None = None,
        role: str = "owner",
        **_: Any,
    ) -> Any:
        account = SimpleNamespace(
            id=telegram_user_id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_username=telegram_username,
            role=role,
        )
        state["upserted"] = account
        return account

    async def fake_issue(account_id: int, **_: Any) -> Any:
        state["issued_for"] = account_id
        return SimpleNamespace(token="RAW-TOKEN-123", account_id=account_id, issued_at=None)

    async def fake_get_last_issued_at(account_id: int, **_: Any) -> Any:
        _ = account_id
        return state["last_issued_at"]

    async def fake_has_completed_web_login(account_id: int, **_: Any) -> bool:
        _ = account_id
        return bool(state["web_login_done"])

    monkeypatch.setattr(access, "is_allowed_admin", fake_is_allowed_admin)
    monkeypatch.setattr(access, "invalidate", fake_invalidate)
    monkeypatch.setattr(access, "resolve_operator_account", fake_resolve_operator_account)
    monkeypatch.setattr(svc, "upsert_account", fake_upsert_account)
    monkeypatch.setattr(svc, "issue_web_auth_token", fake_issue)
    monkeypatch.setattr(svc, "get_last_issued_at", fake_get_last_issued_at)
    monkeypatch.setattr(svc, "has_completed_web_login", fake_has_completed_web_login)
    return state


@pytest.mark.asyncio
async def test_operator_gets_token(env: dict[str, Any]) -> None:
    env["allowed"] = True
    env["operator_account"] = SimpleNamespace(
        id=42,
        telegram_user_id=42,
        telegram_username="owner",
        telegram_chat_id=42,
        role="owner",
    )

    reply = await svc.issue_auth_token_reply(user_id=42, chat_id=42, username="owner")

    assert reply.role == "owner"
    assert reply.account_id == 42
    assert env["issued_for"] == 42
    assert env["upserted"] is None  # оператор уже привязан — upsert_account тут не звонит
    assert reply.token == "RAW-TOKEN-123"  # сырой токен, без подписей
    assert reply.cooldown_remaining is None


@pytest.mark.asyncio
async def test_stranger_always_becomes_member(env: dict[str, Any]) -> None:
    """Незнакомец без совпадения с env-allowlist всегда заводится как member — независимо от
    того, привязан ли уже владелец инсталляции (bootstrap «первый нажавший = владелец» убран,
    см. docstring модуля)."""
    env["allowed"] = False

    reply = await svc.issue_auth_token_reply(user_id=99, chat_id=99, username="stranger")

    assert reply.role == "member"
    upserted = env["upserted"]
    assert upserted is not None
    assert upserted.role == "member"
    assert upserted.telegram_user_id == 99
    assert env["invalidated"] is True
    assert env["issued_for"] == 99
    assert reply.token == "RAW-TOKEN-123"


@pytest.mark.asyncio
async def test_reissue_keeps_same_account(env: dict[str, Any]) -> None:
    env["allowed"] = True
    env["operator_account"] = SimpleNamespace(
        id=42,
        telegram_user_id=42,
        telegram_username="owner",
        telegram_chat_id=42,
        role="owner",
    )

    first = await svc.issue_auth_token_reply(user_id=42, chat_id=42, username="owner")
    second = await svc.issue_auth_token_reply(user_id=42, chat_id=42, username="owner")

    assert first.account_id == 42 and second.account_id == 42
    assert env["issued_for"] == 42


@pytest.mark.asyncio
async def test_reissue_within_cooldown_returns_no_new_token(env: dict[str, Any]) -> None:
    """Повторное нажатие в пределах часа → новый токен НЕ выпускается (cooldown).

    Источник даты — `get_last_issued_at` (Part C: сессии, не колонка `accounts`)."""
    from datetime import UTC, datetime, timedelta

    env["allowed"] = True
    env["operator_account"] = SimpleNamespace(
        id=42,
        telegram_user_id=42,
        telegram_username="owner",
        telegram_chat_id=42,
        role="owner",
    )
    env["last_issued_at"] = datetime.now(UTC) - timedelta(minutes=10)

    reply = await svc.issue_auth_token_reply(user_id=42, chat_id=42, username="owner")

    assert reply.token is None
    assert reply.cooldown_remaining is not None
    assert env["issued_for"] is None  # issue_web_auth_token не звали


@pytest.mark.asyncio
async def test_reissue_within_cooldown_if_never_logged_into_web(env: dict[str, Any]) -> None:
    """Потерял сообщение бота до первого входа — cooldown не должен запирать на час."""
    from datetime import UTC, datetime, timedelta

    env["allowed"] = False
    env["web_login_done"] = False
    env["last_issued_at"] = datetime.now(UTC) - timedelta(minutes=5)

    reply = await svc.issue_auth_token_reply(user_id=99, chat_id=99, username="newbie")

    assert reply.token == "RAW-TOKEN-123"
    assert reply.role == "member"
    assert env["issued_for"] == 99


@pytest.mark.asyncio
async def test_reissue_after_cooldown_issues_new_token(env: dict[str, Any]) -> None:
    """По истечении часа перевыпуск разрешён (новое устройство)."""
    from datetime import UTC, datetime, timedelta

    env["allowed"] = True
    env["operator_account"] = SimpleNamespace(
        id=42,
        telegram_user_id=42,
        telegram_username="owner",
        telegram_chat_id=42,
        role="owner",
    )
    env["last_issued_at"] = datetime.now(UTC) - timedelta(hours=2)

    reply = await svc.issue_auth_token_reply(user_id=42, chat_id=42, username="owner")

    assert reply.token == "RAW-TOKEN-123"
    assert reply.cooldown_remaining is None
    assert env["issued_for"] == 42
