"""Вкладка «Автоматизация» дровера пользователя (админка): сборка `load_user_pipeline` и
операторские мутации (пауза / возобновление / очистка очереди) — все пишут audit."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities.discovery_session import DiscoveryConfig, DiscoveryStatus
from core.domains.pipeline.auto_apply.config import AutoApplyConfig, AutoApplyPlatformConfig
from core.domains.pipeline.auto_apply.queue import AutoApplyQueuePreview
from core.platform.admin import service as svc


class _Job:
    def __init__(self, vacancy_id: str, anketa: dict | None = None) -> None:
        self.id = hash(vacancy_id) & 0xFFFF
        self.vacancy_id = vacancy_id
        self.anketa = anketa


def _preview(platform: str, auto: int, manual: int, pending: int) -> AutoApplyQueuePreview:
    auto_jobs = [_Job(f"{platform}-a{i}") for i in range(auto)]
    manual_jobs = [
        _Job(f"{platform}-m{i}", anketa={"status": "pending"} if i < pending else None)
        for i in range(manual)
    ]
    return AutoApplyQueuePreview(
        platform=platform,  # type: ignore[arg-type]
        enabled=True,
        auto=auto_jobs,
        manual_review=manual_jobs,
        applied=[],
        failure_reasons={},
    )


async def test_load_user_pipeline_assembles_per_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_fetchrow", AsyncMock(return_value={"account_id": 3}))
    monkeypatch.setattr(svc, "_extension_tick_seconds", AsyncMock(return_value=300))
    monkeypatch.setattr(svc, "_extension_discovery_tick_seconds", AsyncMock(return_value=60))

    aa_config = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(
            enabled=True, min_score=70, manual_review_band=10, daily_cap=5
        ),
        getmatch=AutoApplyPlatformConfig(enabled=False),
    )
    d_config = DiscoveryConfig()
    d_config.hh.daily_cap = 60
    d_config.hh.search_urls = ["https://hh.ru/search?x=1", " "]

    monkeypatch.setattr(
        "core.domains.pipeline.auto_apply.get_auto_apply_config",
        AsyncMock(return_value=aa_config),
    )
    monkeypatch.setattr(
        "core.domains.opportunities.discovery_session.get_discovery_config",
        AsyncMock(return_value=d_config),
    )

    async def fake_status(platform, *, account_id):
        state = "running" if platform == "hh" else "idle"
        return DiscoveryStatus(
            platform=platform,
            state=state,
            opened=12 if platform == "hh" else 0,
            daily_used=45 if platform == "hh" else 0,
            daily_cap=200 if platform == "hh" else 60,
        )

    monkeypatch.setattr(
        "core.domains.opportunities.discovery_session.get_discovery_status",
        AsyncMock(side_effect=fake_status),
    )

    async def fake_preview(platform, *, account_id):
        return _preview(platform, auto=3 if platform == "hh" else 0, manual=2, pending=1)

    monkeypatch.setattr(
        "core.domains.pipeline.auto_apply.preview_queue", AsyncMock(side_effect=fake_preview)
    )
    monkeypatch.setattr(
        "core.domains.pipeline.auto_apply.count_today",
        AsyncMock(side_effect=lambda platform, *, account_id: 4 if platform == "hh" else 0),
    )
    monkeypatch.setattr(
        "core.domains.pipeline.auto_apply.runtime_state.get_last_tick",
        AsyncMock(return_value={"at": "2026-08-28T11:55:00+00:00"}),
    )
    monkeypatch.setattr(
        "core.domains.opportunities.discovery_session.get_last_runner_tick",
        AsyncMock(return_value=None),
    )

    result = await svc.load_user_pipeline(3)

    hh = next(p for p in result.platforms if p.platform == "hh")
    assert hh.discovery_state == "running"
    assert hh.discovery_search_urls == 1  # пустая строка отфильтрована
    assert hh.discovery_opened_session == 12
    assert hh.discovery_used_today == 45
    assert hh.discovery_daily_cap == 200  # жёсткий потолок hh, не dc.daily_cap
    assert hh.auto_apply_enabled is True
    assert hh.auto_apply_daily_cap == 150  # жёсткий потолок hh
    assert hh.auto_apply_min_score == 70
    assert hh.auto_apply_manual_band == 10
    assert hh.queue_auto == 3
    assert hh.queue_manual == 2
    assert hh.pending_confirm == 1
    assert hh.applied_today == 4
    assert result.any_discovery_running is True
    assert result.any_auto_apply_enabled is True
    assert result.discovery_tick_seconds == 60
    assert result.auto_apply_last_tick_at is not None
    assert result.auto_apply_next_tick_eta is not None


async def test_load_user_pipeline_404_when_no_account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "_fetchrow", AsyncMock(return_value=None))
    with pytest.raises(svc.AdminError) as exc:
        await svc.load_user_pipeline(999)
    assert exc.value.status == 404


async def test_pause_user_auto_apply_calls_scenario_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(svc, "get_account_by_id", AsyncMock(return_value=object()))
    log_mock = AsyncMock()
    monkeypatch.setattr(svc, "_log_action", log_mock)
    pause_mock = AsyncMock()
    monkeypatch.setattr("core.app.scenarios.auto_apply.pause_all", pause_mock)

    await svc.pause_user_auto_apply(7, actor_id=1)

    pause_mock.assert_awaited_once_with(account_id=7)
    log_mock.assert_awaited_once()
    assert log_mock.await_args.args[0] == "auto_apply_pause"
    assert log_mock.await_args.kwargs["target_account_id"] == 7


async def test_resume_user_auto_apply_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_account_by_id", AsyncMock(return_value=None))
    with pytest.raises(svc.AdminError):
        await svc.resume_user_auto_apply(404, actor_id=1)


async def test_clear_user_auto_apply_queue_returns_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "get_account_by_id", AsyncMock(return_value=object()))
    monkeypatch.setattr(svc, "_log_action", AsyncMock())
    monkeypatch.setattr("core.app.scenarios.auto_apply.clear_queue", AsyncMock(return_value=6))

    cleared = await svc.clear_user_auto_apply_queue(7, actor_id=1)
    assert cleared == 6
