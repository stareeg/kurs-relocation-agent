"""Флаг ручной отправки автооткликов (кнопка «Отправить» в «Расширении»).

Прод-инцидент 2026-08-31: `POST /manual-send` ставил флаг и падал на `NameError: event`
(импорт забыли, CI не запускался). Флаг оставался взведённым, а `GET /preview` из-за него
уходил в ту же необъявленную функцию — 500 на каждый опрос, страница «Расширение» мертва,
раннер получал `preview_http_500` и не работал вовсе, `clear-manual-send` тоже 500.
Здесь: (1) все три ручки роутера реально вызываемы, (2) взведённый флаг сам протухает.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.domains.pipeline.auto_apply import runtime_state as rs


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_get(key: str, default: Any = None, *, account_id: Any = None, db: Any = None) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        store[key] = value

    monkeypatch.setattr(rs, "get_setting", fake_get)
    monkeypatch.setattr(rs, "set_setting", fake_set)
    return store


async def test_not_pending_by_default(settings_store: dict[str, Any]) -> None:
    assert await rs.is_manual_send_pending(account_id=9) is False


async def test_set_then_pending(settings_store: dict[str, Any]) -> None:
    await rs.set_manual_send_pending(True, account_id=9)
    assert await rs.is_manual_send_pending(account_id=9) is True


async def test_clear_removes_flag(settings_store: dict[str, Any]) -> None:
    await rs.set_manual_send_pending(True, account_id=9)
    await rs.set_manual_send_pending(False, account_id=9)
    assert await rs.is_manual_send_pending(account_id=9) is False


async def test_stale_request_expires(settings_store: dict[str, Any]) -> None:
    """Раннер мог не прийти вообще (браузер закрыт, площадки выключены) — просьба протухает,
    а не ждёт неделю, чтобы внезапно отправить боевые отклики."""
    stale = datetime.now(UTC) - timedelta(seconds=rs.MANUAL_SEND_TTL_S + 60)
    settings_store[rs.KEY_RUNTIME_STATE] = {"manual_send_pending": stale.isoformat()}
    assert await rs.is_manual_send_pending(account_id=9) is False


async def test_fresh_request_within_ttl(settings_store: dict[str, Any]) -> None:
    fresh = datetime.now(UTC) - timedelta(seconds=rs.MANUAL_SEND_TTL_S / 2)
    settings_store[rs.KEY_RUNTIME_STATE] = {"manual_send_pending": fresh.isoformat()}
    assert await rs.is_manual_send_pending(account_id=9) is True


async def test_legacy_bool_marker_still_read(settings_store: dict[str, Any]) -> None:
    """Записи до 2026-08-31 хранили голый `true` — их надо уметь прочитать и снять."""
    settings_store[rs.KEY_RUNTIME_STATE] = {"manual_send_pending": True}
    assert await rs.is_manual_send_pending(account_id=9) is True
    await rs.set_manual_send_pending(False, account_id=9)
    assert await rs.is_manual_send_pending(account_id=9) is False


async def test_garbage_marker_is_not_pending(settings_store: dict[str, Any]) -> None:
    settings_store[rs.KEY_RUNTIME_STATE] = {"manual_send_pending": "не дата"}
    assert await rs.is_manual_send_pending(account_id=9) is False


async def test_flag_does_not_clobber_platform_state(settings_store: dict[str, Any]) -> None:
    await rs.mark_platform_limit("hh", account_id=9)
    await rs.set_manual_send_pending(True, account_id=9)
    assert await rs.is_platform_limited_today("hh", account_id=9) is True
    assert await rs.is_manual_send_pending(account_id=9) is True
