"""Kill switch автооткликов (Фаза 7.4, расширен 2026-08-19 пункт 8): pause_all гасит enabled на
всех площадках автооткликов И останавливает идущие сессии автопросмотра разом."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.app.scenarios import auto_apply as scenario
from core.domains.opportunities.discovery_session import DiscoveryStatus
from core.domains.pipeline.auto_apply.config import AutoApplyConfig, AutoApplyPlatformConfig


async def test_pause_all_disables_every_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    current = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=True, min_score=80),
        getmatch=AutoApplyPlatformConfig(enabled=True, dry_run=False, daily_cap=10),
        habr=AutoApplyPlatformConfig(enabled=False),
    )
    get_mock = AsyncMock(return_value=current)
    set_mock = AsyncMock()
    monkeypatch.setattr(scenario, "get_auto_apply_config", get_mock)
    monkeypatch.setattr(scenario, "set_auto_apply_config", set_mock)

    result = await scenario.pause_all(account_id=7)

    assert result.hh.enabled is False
    assert result.getmatch.enabled is False
    assert result.habr.enabled is False
    # Остальные настройки площадки не тронуты — только enabled.
    assert result.hh.min_score == 80
    assert result.getmatch.dry_run is False
    assert result.getmatch.daily_cap == 10
    get_mock.assert_awaited_once_with(account_id=7)
    set_mock.assert_awaited_once_with(result, account_id=7)


async def test_resume_all_enables_every_platform_without_touching_other_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Операторская ручка «Возобновить» из админки: enabled=True на всех площадках, режим
    (dry_run/min_score/daily_cap) не трогаем — не было настроек, dry_run по дефолту True."""
    current = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=False, dry_run=False, min_score=82, daily_cap=7),
        getmatch=AutoApplyPlatformConfig(enabled=False),
        habr=AutoApplyPlatformConfig(enabled=False),
    )
    monkeypatch.setattr(scenario, "get_auto_apply_config", AsyncMock(return_value=current))
    set_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_auto_apply_config", set_mock)

    result = await scenario.resume_all(account_id=5)

    assert result.hh.enabled is True
    assert result.getmatch.enabled is True
    assert result.habr.enabled is True
    assert result.hh.dry_run is False  # был снят владельцем — не трогаем
    assert result.hh.min_score == 82
    assert result.hh.daily_cap == 7
    assert result.getmatch.dry_run is True  # дефолт — безопасный режим проверки
    set_mock.assert_awaited_once_with(result, account_id=5)


async def test_pause_all_noop_when_already_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    current = AutoApplyConfig()
    monkeypatch.setattr(scenario, "get_auto_apply_config", AsyncMock(return_value=current))
    set_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_auto_apply_config", set_mock)

    result = await scenario.pause_all(account_id=1)

    assert result.hh.enabled is False
    assert result.getmatch.enabled is False
    assert result.habr.enabled is False
    set_mock.assert_awaited_once()


async def test_pause_all_also_stops_running_discovery_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Инцидент 2026-08-19: «Стоп всё» жила только в домене автооткликов — владелец жал кнопку,
    ожидая, что остановится всё под шапкой «Расширения», а вкладки автопросмотра продолжали
    открываться. Теперь kill switch гасит и её."""
    empty_config = AsyncMock(return_value=AutoApplyConfig())
    monkeypatch.setattr(scenario, "get_auto_apply_config", empty_config)
    monkeypatch.setattr(scenario, "set_auto_apply_config", AsyncMock())

    statuses = {
        "hh": DiscoveryStatus(platform="hh", state="running"),
        "getmatch": DiscoveryStatus(platform="getmatch", state="idle"),
        "habr": DiscoveryStatus(platform="habr", state="paused_by_user"),
    }

    async def fake_status(platform: str, *, account_id: int) -> DiscoveryStatus:
        _ = account_id
        return statuses[platform]

    status_mock = AsyncMock(side_effect=fake_status)
    stop_mock = AsyncMock()
    monkeypatch.setattr(scenario, "get_discovery_status", status_mock)
    monkeypatch.setattr(scenario, "stop_session", stop_mock)

    await scenario.pause_all(account_id=3)

    # running/paused_* — остановлены; idle (getmatch) — не тронут лишним вызовом.
    stop_mock.assert_any_await("hh", account_id=3)
    stop_mock.assert_any_await("habr", account_id=3)
    assert stop_mock.await_count == 2
