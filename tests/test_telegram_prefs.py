"""TB-2.1: telegram_prefs — дефолты, парсинг, round-trip через мокнутый repo."""

from __future__ import annotations

from typing import Any

import pytest

from core.app.settings_defaults import default_app_settings_values
from core.domains.profile import telegram_prefs as tp


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: Any = None, db: Any = None) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        store[key] = value

    monkeypatch.setattr(tp, "get_setting", fake_get)
    monkeypatch.setattr(tp, "set_setting", fake_set)
    return store


def test_defaults_match_plan() -> None:
    prefs = tp.TelegramPrefs()
    assert prefs.digest == "smart"
    assert prefs.warmup_summary == "results"
    assert prefs.card_style == "image"
    assert prefs.batch_cleanup == "auto"
    assert tp.default_telegram_prefs_dict() == prefs.model_dump()


def test_default_app_settings_includes_telegram_prefs() -> None:
    values = default_app_settings_values()
    assert values["telegram_prefs"] == tp.default_telegram_prefs_dict()


def test_prefs_from_mapping_empty_and_garbage() -> None:
    assert tp.prefs_from_mapping(None) == tp.TelegramPrefs()
    assert tp.prefs_from_mapping("x") == tp.TelegramPrefs()
    assert tp.prefs_from_mapping({"digest": "nope"}) == tp.TelegramPrefs()


def test_prefs_from_mapping_partial_merges_defaults() -> None:
    prefs = tp.prefs_from_mapping({"digest": "off"})
    assert prefs.digest == "off"
    assert prefs.warmup_summary == "results"
    assert prefs.card_style == "image"
    assert prefs.batch_cleanup == "auto"


def test_prefs_from_mapping_full() -> None:
    prefs = tp.prefs_from_mapping(
        {
            "digest": "always",
            "warmup_summary": "always",
            "card_style": "text",
            "batch_cleanup": "auto",
            "extra_ignored": 1,
        }
    )
    assert prefs == tp.TelegramPrefs(
        digest="always",
        warmup_summary="always",
        card_style="text",
        batch_cleanup="auto",
    )


@pytest.mark.asyncio
async def test_get_prefs_missing_key_returns_defaults(
    settings_store: dict[str, Any],
) -> None:
    prefs = await tp.get_telegram_prefs(account_id=1)
    assert prefs == tp.TelegramPrefs()
    assert tp.KEY_PREFS not in settings_store


@pytest.mark.asyncio
async def test_set_and_get_roundtrip(settings_store: dict[str, Any]) -> None:
    written = tp.TelegramPrefs(
        digest="off",
        warmup_summary="off",
        card_style="text",
        batch_cleanup="off",
    )
    await tp.set_telegram_prefs(written, account_id=1)
    assert settings_store[tp.KEY_PREFS] == written.model_dump()
    loaded = await tp.get_telegram_prefs(account_id=1)
    assert loaded == written
