"""Вердикт «что не так»: порядок проверок, пустая установка, ключ не течёт."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.platform.admin.diagnosis import build_diagnosis, diagnosis_contains_secret, version_older
from core.platform.admin.models import AdminAccountSnapshot, AdminDiagnosis, AdminUserRow


def _empty_user() -> AdminUserRow:
    return AdminUserRow(
        account_id=4,
        telegram_username="kate",
        telegram_user_id=100,
        role="member",
        status="active",
    )


def test_check_order_on_empty_install() -> None:
    items = build_diagnosis(
        has_key=False,
        has_resume=False,
        extension_confirmed=False,
        telegram_chat_id=None,
        errors_24h=0,
        spend_alert=False,
    )
    assert [item.id for item in items] == [
        "key",
        "resume",
        "extension",
        "telegram",
        "errors",
        "last_score",
        "spend",
    ]
    by_id = {item.id: item for item in items}
    assert by_id["key"].ok is False and by_id["key"].action_kind == "issue_key"
    assert by_id["resume"].ok is False
    assert by_id["extension"].ok is False
    assert by_id["telegram"].ok is False
    assert by_id["errors"].ok is True
    assert by_id["last_score"].ok is True
    assert by_id["spend"].ok is True


def test_healthy_account_all_ok() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    items = build_diagnosis(
        has_key=True,
        key_alive=True,
        has_resume=True,
        search_title="Backend",
        extension_confirmed=True,
        last_extension_at=now - timedelta(hours=2),
        extension_version="1.4.0",
        current_extension_version="1.4.0",
        telegram_chat_id=11,
        errors_24h=0,
        last_scored_at=now - timedelta(hours=3),
        spend_alert=False,
        now=now,
    )
    assert all(item.ok for item in items)
    assert [item.id for item in items][:4] == ["key", "key_alive", "resume", "search_profile"]


def test_dead_key_and_stale_extension() -> None:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    items = build_diagnosis(
        has_key=True,
        key_alive=False,
        has_resume=True,
        search_title="",
        extension_confirmed=True,
        last_extension_at=now - timedelta(days=20),
        extension_version="1.2.0",
        current_extension_version="1.4.0",
        telegram_chat_id=11,
        errors_24h=4,
        last_scored_at=now - timedelta(days=30),
        spend_alert=True,
        spend_month_usd=12.5,
        now=now,
    )
    by_id = {item.id: item for item in items}
    assert by_id["key_alive"].ok is False
    assert by_id["search_profile"].ok is False
    assert by_id["extension"].ok is False
    assert by_id["extension_version"].ok is False
    assert by_id["errors"].ok is False and by_id["errors"].action_kind == "journal"
    assert by_id["last_score"].ok is False
    assert by_id["spend"].ok is False


def test_raw_key_never_enters_diagnosis() -> None:
    secret = "sk-or-v1-this-is-the-secret-key-value-abcdef"
    items = build_diagnosis(
        has_key=True,
        key_alive=True,
        has_resume=False,
        extension_confirmed=False,
        telegram_chat_id=None,
    )
    dumped = AdminDiagnosis(items=items).model_dump_json()
    assert secret not in dumped
    assert not diagnosis_contains_secret(items, secret)
    snap = AdminAccountSnapshot(search_title=secret, extension_version="1")
    assert snap.search_title == secret


def test_version_older() -> None:
    assert version_older("1.2.0", "1.4.0") is True
    assert version_older("1.4.0", "1.4.0") is False
    assert version_older("1.5.0", "1.4.0") is False
    assert version_older("", "1.4.0") is False
