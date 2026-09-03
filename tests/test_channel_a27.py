"""A-27: порт Channel — web/telegram/extension без своей логики; один сценарий с двух каналов."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.app.channels import (
    EXTENSION,
    TELEGRAM,
    WEB,
    SurfaceChannel,
    register_builtin_channels,
    set_stage_via,
    skip_via,
)
from core.domains.opportunities.jobs import Job
from core.kernel import ports
from tests.fakes import FakeChannel


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def test_builtin_channels_register_and_satisfy_protocol():
    register_builtin_channels()
    for name, expected in (
        ("web", WEB),
        ("telegram", TELEGRAM),
        ("extension", EXTENSION),
    ):
        ch = ports.channel(name)
        assert isinstance(ch, ports.Channel)
        assert ch.name == expected.name
        assert ch.source_tag == expected.source_tag


def test_unknown_channel_raises():
    with pytest.raises(ports.PortNotBoundError):
        ports.channel("sms")


def test_surface_channel_is_channel_protocol():
    assert isinstance(WEB, ports.Channel)
    assert isinstance(FakeChannel("web"), ports.Channel)


async def test_same_scenario_called_from_two_channels(monkeypatch: pytest.MonkeyPatch):
    """Приёмка A-27: web и telegram зовут один и тот же сценарий skip_job."""
    calls: list[tuple[int, str]] = []

    async def _fake_skip(job_id: int, reason: str, *, account_id: int) -> Job:
        calls.append((job_id, reason))
        return Job(id=job_id, vacancy_id="v1", vacancy_text="x" * 60, status="Просмотр")

    monkeypatch.setattr("core.app.channels.skip_job", _fake_skip)

    assert isinstance(WEB, ports.Channel)
    assert isinstance(TELEGRAM, ports.Channel)

    await skip_via(WEB, 7, "низкая вилка", account_id=1)
    await skip_via(TELEGRAM, 7, "низкая вилка", account_id=1)

    assert calls == [(7, "низкая вилка"), (7, "низкая вилка")]


async def test_set_stage_passes_channel_source_tag(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []

    async def _fake_set(
        job_id: int, stage: str, *, source: str = "api_kanban", account_id: int
    ) -> Job:
        seen.append(source)
        return Job(id=job_id, vacancy_id="v1", vacancy_text="x" * 60, status=stage)

    monkeypatch.setattr("core.app.channels.set_job_stage", _fake_set)

    await set_stage_via(WEB, 1, "Отклик", account_id=1)
    await set_stage_via(TELEGRAM, 1, "Отклик", account_id=1)
    await set_stage_via(EXTENSION, 1, "Отклик", account_id=1)

    assert seen == ["api_kanban", "telegram_bot", "vacancy_page"]


async def test_fake_channels_share_scenario(monkeypatch: pytest.MonkeyPatch):
    """Два произвольных канала (не только builtin) — тот же skip_via."""
    mock_skip = AsyncMock(
        return_value=Job(id=3, vacancy_id="gm_1", vacancy_text="y" * 60, status="Просмотр")
    )
    monkeypatch.setattr("core.app.channels.skip_job", mock_skip)

    a = SurfaceChannel(name="a", source_tag="a_tag")
    b = SurfaceChannel(name="b", source_tag="b_tag")
    ports.register_channel(a)
    ports.register_channel(b)

    await skip_via(ports.channel("a"), 3, "причина", account_id=1)
    await skip_via(ports.channel("b"), 3, "причина", account_id=1)
    assert mock_skip.await_count == 2
    mock_skip.assert_awaited_with(3, "причина", account_id=1)
