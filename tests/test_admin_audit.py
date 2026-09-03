"""Админ-аудит: сырой ключ не течёт в details."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from core.platform.admin import audit as admin_audit
from core.platform.admin.service import issue_user_key
from core.platform.openrouter_keys import mask_key

_RAW_KEY = "sk-or-v1-this-is-the-secret-key-value-abcdef"


def test_sanitize_details_replaces_raw_key_with_mask() -> None:
    clean = admin_audit.sanitize_details({"key": _RAW_KEY, "hours": 24, "reason": "тест"})
    dumped = json.dumps(clean)
    assert _RAW_KEY not in dumped
    assert clean["key_hint"] == mask_key(_RAW_KEY)
    assert "key" not in clean
    assert clean["hours"] == 24


def test_sanitize_details_masks_sk_or_value_in_any_field() -> None:
    clean = admin_audit.sanitize_details({"note": _RAW_KEY})
    assert clean["note"] == mask_key(_RAW_KEY)
    assert _RAW_KEY not in json.dumps(clean)


@pytest.mark.asyncio
async def test_log_action_writes_audit_and_keeps_event(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, object]] = []

    async def fake_record(**kwargs: object) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr("core.platform.admin.service.record_audit", fake_record)
    from core.platform.admin import service as admin_svc

    await admin_svc._log_action("disable", 1, target_account_id=2, reason="тест", key=_RAW_KEY)
    assert len(recorded) == 1
    row = recorded[0]
    assert row["actor_id"] == 1
    assert row["action"] == "disable"
    assert row["target_id"] == 2
    details = row["details"]
    assert isinstance(details, dict)
    assert details["reason"] == "тест"
    assert _RAW_KEY not in json.dumps(details)
    assert details["key_hint"] == mask_key(_RAW_KEY)


@pytest.mark.asyncio
async def test_key_issue_audit_has_mask_not_raw_key(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[dict[str, object]] = []

    async def fake_record(**kwargs: object) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr("core.platform.admin.service.record_audit", fake_record)
    import core.platform.admin.service as admin_svc

    monkeypatch.setattr(admin_svc.openrouter_keys, "issue_key", AsyncMock())
    monkeypatch.setattr(admin_svc.openrouter_keys, "notify_key_issued", AsyncMock())
    await issue_user_key(2, _RAW_KEY, actor_id=1, label="prod")
    assert recorded
    dumped = json.dumps(recorded[0]["details"])
    assert _RAW_KEY not in dumped
    assert recorded[0]["action"] == "key_issue"
    assert recorded[0]["details"]["key_hint"] == mask_key(_RAW_KEY)
    assert _RAW_KEY[:16] not in dumped
