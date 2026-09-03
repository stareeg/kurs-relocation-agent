"""Этап 4: жизненный цикл аккаунта в админ-консоли.

Причина отключения сохраняется, последнего owner нельзя разжаловать, себя отключить
нельзя, заметка оператора не течёт в неадминские ручки и не живёт в AccountRecord.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.schemas.auth import AuthStatusResponse
from api.schemas.resume import AppSettingsResponse, AppSettingsUpdate
from core.platform.admin.models import AdminError
from core.platform.admin.service import (
    disable_user,
    enable_user,
    search_profile_lines,
    set_user_note,
    set_user_role,
)
from core.platform.repo.accounts import _COLUMNS, AccountRecord
from tests.fake_accounts import FakeAccountsStore


def _patch(store: FakeAccountsStore, monkeypatch: pytest.MonkeyPatch):
    import core.platform.admin.service as admin_svc

    store.patch_accounts_module(monkeypatch, admin_svc)

    async def fake_revoke(account_id: int) -> int:
        return await store.revoke_all_sessions(account_id)

    monkeypatch.setattr(admin_svc, "_revoke_sessions", fake_revoke)
    monkeypatch.setattr(admin_svc, "_log_action", AsyncMock())
    return admin_svc


@pytest.mark.asyncio
async def test_disable_saves_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    member = await store.upsert_account(
        telegram_user_id=2, telegram_username="friend", role="member"
    )
    _patch(store, monkeypatch)

    await disable_user(member.id, actor_id=owner.id, reason="  тестирует getmatch  ")
    row = store._rows[member.id]
    assert row["status"] == "disabled"
    assert row["disabled_reason"] == "тестирует getmatch"
    assert row["disabled_at"] is not None

    await enable_user(member.id, actor_id=owner.id)
    row = store._rows[member.id]
    assert row["status"] == "active"
    assert row["disabled_reason"] is None
    assert row["disabled_at"] is None


@pytest.mark.asyncio
async def test_disable_self_still_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    _patch(store, monkeypatch)
    with pytest.raises(AdminError) as exc:
        await disable_user(owner.id, actor_id=owner.id, reason="проверка")
    assert "свой" in exc.value.message
    assert store._rows[owner.id]["status"] == "active"


@pytest.mark.asyncio
async def test_cannot_demote_last_active_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    member = await store.upsert_account(
        telegram_user_id=2, telegram_username="friend", role="member"
    )
    _patch(store, monkeypatch)

    with pytest.raises(AdminError) as exc:
        await set_user_role(owner.id, "member", actor_id=owner.id)
    assert "последнего" in exc.value.message
    assert (await store.get_account_by_id(owner.id)).role == "owner"

    await set_user_role(member.id, "owner", actor_id=owner.id)
    assert (await store.get_account_by_id(member.id)).role == "owner"
    await set_user_role(owner.id, "member", actor_id=member.id)
    assert (await store.get_account_by_id(owner.id)).role == "member"

    with pytest.raises(AdminError):
        await set_user_role(member.id, "member", actor_id=member.id)


@pytest.mark.asyncio
async def test_note_stays_on_account_row_not_record(monkeypatch: pytest.MonkeyPatch) -> None:
    store = FakeAccountsStore()
    owner = await store.upsert_account(telegram_user_id=1, telegram_username="op", role="owner")
    member = await store.upsert_account(
        telegram_user_id=2, telegram_username="friend", role="member"
    )
    _patch(store, monkeypatch)

    await set_user_note(member.id, "  Катя, тестирует  ", actor_id=owner.id)
    assert store._rows[member.id]["note"] == "Катя, тестирует"
    record = await store.get_account_by_id(member.id)
    assert record is not None
    assert not hasattr(record, "note")


def test_operator_fields_do_not_leak_to_non_admin_apis() -> None:
    """Заметка — только админ-витрина. /auth/status и /api/settings её не знают."""
    assert "note" not in AccountRecord.__dataclass_fields__
    assert "disabled_reason" not in AccountRecord.__dataclass_fields__
    assert "disabled_at" not in AccountRecord.__dataclass_fields__
    assert "note" not in _COLUMNS
    assert "note" not in AuthStatusResponse.model_fields
    assert "note" not in AppSettingsResponse.model_fields
    assert "note" not in AppSettingsUpdate.model_fields
    assert "spend_alert_usd" not in AppSettingsResponse.model_fields
    assert "admin_spend_alert_usd" not in AppSettingsUpdate.model_fields


@pytest.mark.parametrize(
    "resume,expected",
    [
        (None, ("", "", "")),
        ({}, ("", "", "")),
        (
            {"position": {"title": "  PM  ", "grade": ["senior"], "schedule": ["удалёнка"]}},
            ("PM", "senior", "удалёнка"),
        ),
        (
            {"position": {"title": "IC", "grade": "lead", "schedule": ["", "гибрид"]}},
            ("IC", "lead", "гибрид"),
        ),
        ('{"position": {"title": "Dev"}}', ("Dev", "", "")),
    ],
)
def test_search_profile_lines_from_resume_jsonb(
    resume: object, expected: tuple[str, str, str]
) -> None:
    assert search_profile_lines(resume) == expected


@pytest.mark.asyncio
async def test_user_detail_snapshot_from_resume_not_domain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Снимок читает jsonb резюме локально — без derive_search_profile."""
    import core.platform.admin.service as admin_svc

    async def fake_fetchrow(sql: str, *args: object, name: str = "", **kwargs: object):
        _ = sql, args, kwargs
        if name == "карточка человека":
            return {
                "account_id": 2,
                "telegram_username": "friend",
                "telegram_user_id": 20,
                "role": "member",
                "status": "active",
                "session_count": 3,
            }
        if name == "резюме человека":
            return {
                "updated_at": None,
                "bytes": 42,
                "data": {
                    "position": {
                        "title": "PM",
                        "grade": ["senior"],
                        "schedule": ["удалёнка"],
                    }
                },
            }
        if name == "версия расширения":
            return {"version": "1.4.0"}
        if name == "устройства":
            return {"sessions": 3, "devices": 2}
        return None

    async def fake_fetch(sql: str, *args: object, name: str = "", **kwargs: object):
        _ = sql, args, kwargs
        if name == "настройки человека":
            return [
                {"key": "salary_min_override", "value": 300000},
                {"key": "auto_apply_config", "value": {"hh": {"enabled": True}}},
                {"key": "discovery_config", "value": {"getmatch": {"enabled": True}}},
            ]
        return []

    monkeypatch.setattr(admin_svc, "_fetchrow", fake_fetchrow)
    monkeypatch.setattr(admin_svc, "_fetch", fake_fetch)
    detail = await admin_svc.load_user_detail(2)
    assert detail.snapshot.search_title == "PM"
    assert detail.snapshot.search_grades == "senior"
    assert detail.snapshot.search_formats == "удалёнка"
    assert detail.snapshot.extension_version == "1.4.0"
    assert detail.snapshot.device_count == 2
    assert detail.snapshot.salary_min_override == 300000
    assert detail.snapshot.auto_apply is True
    assert detail.snapshot.discovery is True
    assert detail.sessions == 3
