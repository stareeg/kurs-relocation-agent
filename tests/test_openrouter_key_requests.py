"""Жизненный цикл ключа OpenRouter (`core.platform.openrouter_keys`) на фейковых репозиториях.

Раньше эти же сценарии жили в `bot_app/services/openrouter_keys.py` — выдача шла кнопками в
Telegram. С 2026-08-25 заявка приходит с «Аккаунта», а выдаёт оператор из админ-панели, и
проверяем мы поэтому не тексты сообщений, а состояние: что записано в настройки, какое у
ключа происхождение и что стало с заявкой.

Без Postgres и без Telegram-моков: репозитории подменяются двойниками (RLS-поведение самих
таблиц покрыто отдельно — tests/test_rls_openrouter_key_requests.py, маркер `db`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from core.platform import openrouter_keys as svc
from core.platform.repo.accounts import AccountRecord


@dataclass
class _Row:
    id: int
    account_id: int
    status: str
    resolved_by: int | None = None
    note: str | None = None
    requested_at: datetime = datetime(2026, 8, 25, tzinfo=UTC)


class _FakeRequestsRepo:
    """Двойник `core.platform.repo.openrouter_key_requests` (только то, что зовёт сервис)."""

    Status = str

    def __init__(self) -> None:
        self._rows: dict[int, _Row] = {}
        self._next_id = 1

    async def get_own_pending_request(self, account_id: int, **_: Any) -> _Row | None:
        for row in self._rows.values():
            if row.account_id == account_id and row.status in ("pending", "approved"):
                return row
        return None

    async def get_own_latest_request(self, account_id: int, **_: Any) -> _Row | None:
        rows = [r for r in self._rows.values() if r.account_id == account_id]
        return rows[-1] if rows else None

    async def create_request(self, account_id: int, **_: Any) -> _Row:
        row = _Row(id=self._next_id, account_id=account_id, status="pending")
        self._rows[row.id] = row
        self._next_id += 1
        return row

    async def get_request(self, request_id: int, **_: Any) -> _Row | None:
        return self._rows.get(request_id)

    async def close_open_requests(
        self, account_id: int, *, status: str, resolved_by: int, note: str | None = None, **_: Any
    ) -> int:
        closed = 0
        for row in self._rows.values():
            if row.account_id == account_id and row.status in ("pending", "approved"):
                row.status = status
                row.resolved_by = resolved_by
                row.note = note
                closed += 1
        return closed


class _FakeOriginsRepo:
    """Двойник `core.platform.repo.openrouter_account_keys`."""

    def __init__(self) -> None:
        self.rows: dict[int, Any] = {}

    async def get_origin(self, account_id: int, **_: Any) -> Any:
        return self.rows.get(account_id)

    async def upsert_origin(
        self,
        account_id: int,
        *,
        origin: str,
        key_hint: str,
        label: str | None = None,
        issued_by: int | None = None,
        **_: Any,
    ) -> None:
        self.rows[account_id] = _OriginRow(
            account_id=account_id,
            origin=origin,
            key_hint=key_hint,
            label=label,
            issued_by=issued_by,
        )

    async def delete_origin(self, account_id: int, **_: Any) -> None:
        self.rows.pop(account_id, None)

    async def list_origins(self, **_: Any) -> list[Any]:
        return list(self.rows.values())


@dataclass
class _OriginRow:
    account_id: int
    origin: str
    key_hint: str
    label: str | None = None
    issued_by: int | None = None
    issued_at: datetime = datetime(2026, 8, 25, tzinfo=UTC)


def _account(account_id: int, *, role: str = "member", username: str | None = "friend"):
    return AccountRecord(
        id=account_id,
        telegram_user_id=500 + account_id,
        telegram_username=username,
        telegram_chat_id=900 + account_id,
        role=role,  # type: ignore[arg-type]
        status="active",
    )


@pytest.fixture
def requests_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRequestsRepo:
    fake = _FakeRequestsRepo()
    monkeypatch.setattr(svc, "requests", fake)
    return fake


@pytest.fixture
def origins_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeOriginsRepo:
    fake = _FakeOriginsRepo()
    monkeypatch.setattr(svc, "origins", fake)
    return fake


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[tuple[int | None, str], Any]:
    """Подменяет запись/чтение `account_settings` — сервис зовёт их по именам из своего модуля."""
    store: dict[tuple[int | None, str], Any] = {}

    async def fake_set_setting(key: str, value: Any, *, account_id: int | None, **_: Any) -> None:
        if value is None:
            store.pop((account_id, key), None)
        else:
            store[(account_id, key)] = value

    async def fake_is_configured(*, account_id: int | None, **_: Any) -> bool:
        return bool(store.get((account_id, "openrouter_api_key")))

    async def fake_set_at(*, account_id: int | None, **_: Any) -> datetime | None:
        return None

    monkeypatch.setattr(svc, "_set_setting", fake_set_setting)
    monkeypatch.setattr(svc, "is_openrouter_key_configured", fake_is_configured)
    monkeypatch.setattr(svc, "get_openrouter_key_set_at", fake_set_at)
    return store


@pytest.fixture
def accounts_store(monkeypatch: pytest.MonkeyPatch) -> dict[int, AccountRecord]:
    accounts = {7: _account(7), 1: _account(1, role="owner", username="owner")}

    async def fake_get_account_by_id(account_id: int, **_: Any) -> AccountRecord | None:
        return accounts.get(account_id)

    monkeypatch.setattr(svc, "get_account_by_id", fake_get_account_by_id)
    return accounts


pytestmark = pytest.mark.usefixtures("requests_repo", "origins_repo", "settings_store")


# --- Маска ---


def test_mask_key_keeps_prefix_and_tail() -> None:
    assert svc.mask_key("sk-or-v1-0123456789abcdef") == "sk-or-v1-…cdef"


def test_mask_key_strips_newlines_before_masking() -> None:
    assert svc.mask_key("  sk-or-v1-0123456789abcdef\n") == "sk-or-v1-…cdef"


def test_mask_key_hides_short_garbage() -> None:
    """Короткая строка — не ключ; показывать её целиком незачем."""
    assert svc.mask_key("sk-or-v1") == "…"


# --- Заявка ---


@pytest.mark.asyncio
async def test_request_key_creates_pending(
    requests_repo: _FakeRequestsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    outcome = await svc.request_key(account_id=7)

    assert outcome.status == "created"
    assert outcome.request_id == 1
    assert requests_repo._rows[1].status == "pending"


@pytest.mark.asyncio
async def test_request_key_is_idempotent_while_pending(
    requests_repo: _FakeRequestsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    first = await svc.request_key(account_id=7)
    second = await svc.request_key(account_id=7)

    assert first.status == "created"
    assert second.status == "already_pending"
    assert len(requests_repo._rows) == 1


@pytest.mark.asyncio
async def test_request_key_refused_when_key_already_there(
    requests_repo: _FakeRequestsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    await svc.save_own_key(account_id=7, raw_key="sk-or-v1-own")

    outcome = await svc.request_key(account_id=7)

    assert outcome.status == "already_has_key"
    assert requests_repo._rows == {}


@pytest.mark.asyncio
async def test_save_own_key_closes_pending_request(
    requests_repo: _FakeRequestsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    """Вставил свой ключ после «Запросить» — заявка не должна висеть в очереди оператора."""
    await svc.request_key(account_id=7)

    await svc.save_own_key(account_id=7, raw_key="sk-or-v1-own-after-request")

    assert requests_repo._rows[1].status == "fulfilled"
    assert requests_repo._rows[1].resolved_by == 7


# --- Выдача оператором ---


@pytest.mark.asyncio
async def test_issue_key_stores_secret_origin_and_closes_request(
    requests_repo: _FakeRequestsRepo,
    origins_repo: _FakeOriginsRepo,
    settings_store: dict[tuple[int | None, str], Any],
    accounts_store: dict[int, AccountRecord],
) -> None:
    await svc.request_key(account_id=7)

    await svc.issue_key(
        target_account_id=7, raw_key="sk-or-v1-0123456789abcdef", actor_id=1, label="friend-vasya"
    )

    assert settings_store[(7, "openrouter_api_key")] == "sk-or-v1-0123456789abcdef"
    origin = origins_repo.rows[7]
    assert origin.origin == "admin"
    assert origin.key_hint == "sk-or-v1-…cdef"  # маска, не секрет
    assert origin.label == "friend-vasya"
    assert origin.issued_by == 1
    assert requests_repo._rows[1].status == "fulfilled"  # висящая заявка закрылась сама


@pytest.mark.asyncio
async def test_issue_key_rejects_blank(accounts_store: dict[int, AccountRecord]) -> None:
    with pytest.raises(svc.OpenRouterKeyError):
        await svc.issue_key(target_account_id=7, raw_key="   ", actor_id=1)


@pytest.mark.asyncio
async def test_issue_key_rejects_unknown_account(accounts_store: dict[int, AccountRecord]) -> None:
    with pytest.raises(svc.OpenRouterKeyError):
        await svc.issue_key(target_account_id=404, raw_key="sk-or-v1-abcdefghij", actor_id=1)


@pytest.mark.asyncio
async def test_reissue_overwrites_hint(
    origins_repo: _FakeOriginsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    await svc.issue_key(target_account_id=7, raw_key="sk-or-v1-aaaaaaaaaa1111", actor_id=1)
    await svc.issue_key(target_account_id=7, raw_key="sk-or-v1-bbbbbbbbbb2222", actor_id=1)

    assert origins_repo.rows[7].key_hint == "sk-or-v1-…2222"


@pytest.mark.asyncio
async def test_revoke_key_clears_secret_and_origin(
    origins_repo: _FakeOriginsRepo,
    settings_store: dict[tuple[int | None, str], Any],
    accounts_store: dict[int, AccountRecord],
) -> None:
    await svc.issue_key(target_account_id=7, raw_key="sk-or-v1-0123456789abcdef", actor_id=1)

    await svc.revoke_key(target_account_id=7, actor_id=1)

    assert (7, "openrouter_api_key") not in settings_store
    assert 7 not in origins_repo.rows


@pytest.mark.asyncio
async def test_reject_request_closes_it(
    requests_repo: _FakeRequestsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    created = await svc.request_key(account_id=7)
    assert created.request_id is not None

    target = await svc.reject_request(request_id=created.request_id, actor_id=1)

    assert target == 7
    assert requests_repo._rows[created.request_id].status == "rejected"


@pytest.mark.asyncio
async def test_reject_twice_fails(
    requests_repo: _FakeRequestsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    created = await svc.request_key(account_id=7)
    assert created.request_id is not None
    await svc.reject_request(request_id=created.request_id, actor_id=1)

    with pytest.raises(svc.OpenRouterKeyError):
        await svc.reject_request(request_id=created.request_id, actor_id=1)


# --- Свой ключ на «Аккаунте» ---


@pytest.mark.asyncio
async def test_save_own_key_marks_origin_self(
    origins_repo: _FakeOriginsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    await svc.save_own_key(account_id=7, raw_key="sk-or-v1-0123456789abcdef")

    assert origins_repo.rows[7].origin == "self"
    assert origins_repo.rows[7].issued_by is None


@pytest.mark.asyncio
async def test_clear_own_key_removes_self_key(
    origins_repo: _FakeOriginsRepo,
    settings_store: dict[tuple[int | None, str], Any],
    accounts_store: dict[int, AccountRecord],
) -> None:
    await svc.save_own_key(account_id=7, raw_key="sk-or-v1-0123456789abcdef")

    await svc.clear_own_key(account_id=7)

    assert (7, "openrouter_api_key") not in settings_store
    assert 7 not in origins_repo.rows


@pytest.mark.asyncio
async def test_clear_own_key_refuses_admin_issued_key(
    origins_repo: _FakeOriginsRepo,
    settings_store: dict[tuple[int | None, str], Any],
    accounts_store: dict[int, AccountRecord],
) -> None:
    """Ключ выдал оператор — «Сбросить» на «Аккаунте» отключило бы человеку продукт."""
    await svc.issue_key(target_account_id=7, raw_key="sk-or-v1-0123456789abcdef", actor_id=1)

    with pytest.raises(svc.OpenRouterKeyError):
        await svc.clear_own_key(account_id=7)

    assert settings_store[(7, "openrouter_api_key")] == "sk-or-v1-0123456789abcdef"


@pytest.mark.asyncio
async def test_own_key_may_replace_admin_issued_one(
    origins_repo: _FakeOriginsRepo, accounts_store: dict[int, AccountRecord]
) -> None:
    """Уйти с общего ключа на свой биллинг человек вправе — это ничего у него не отнимает."""
    await svc.issue_key(target_account_id=7, raw_key="sk-or-v1-0123456789abcdef", actor_id=1)

    await svc.save_own_key(account_id=7, raw_key="sk-or-v1-mineminemine1111")

    assert origins_repo.rows[7].origin == "self"


# --- Витрина «Аккаунта» ---


@pytest.mark.asyncio
async def test_key_state_reports_admin_origin(accounts_store: dict[int, AccountRecord]) -> None:
    await svc.issue_key(
        target_account_id=7, raw_key="sk-or-v1-0123456789abcdef", actor_id=1, label="friend"
    )

    state = await svc.key_state(7)

    assert state.configured is True
    assert state.origin == "admin"
    assert state.issued_by == 1


@pytest.mark.asyncio
async def test_key_state_reports_pending_request_without_key(
    accounts_store: dict[int, AccountRecord],
) -> None:
    await svc.request_key(account_id=7)

    state = await svc.key_state(7)

    assert state.configured is False
    assert state.origin is None
    assert state.request_status == "pending"
