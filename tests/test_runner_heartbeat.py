"""Heartbeat раннеров расширения (автоотклики / автопросмотр).

Инцидент 2026-08-27..28: раннер молча не тикал 9 часов, в журнале — ничего. Тик-репорт
пишет строку АВТООТКЛИК/АВТОПРОСМОТР (INFO рутинно, WARNING при проблеме, троттл 30 мин) и
`last_tick` в рантайм-стейт для админ-карточки «раннер молчит Nч».
"""

from __future__ import annotations

import logging

import pytest

from core.app.scenarios import auto_apply as aa_scenario
from core.domains.opportunities import discovery_session as disc
from core.platform.repo import settings as settings_repo


class _MemSettings:
    """In-memory замена get_setting/set_setting (account-scoped ключи)."""

    def __init__(self) -> None:
        self.store: dict[tuple[int | None, str], object] = {}

    async def get(self, key, default=None, *, account_id, db=None):
        return self.store.get((account_id, key), default)

    async def set(self, key, value, *, account_id, db=None):
        if value is None:
            self.store.pop((account_id, key), None)
        else:
            self.store[(account_id, key)] = value


@pytest.fixture
def mem(monkeypatch: pytest.MonkeyPatch) -> _MemSettings:
    m = _MemSettings()
    monkeypatch.setattr(settings_repo, "get_setting", m.get)
    monkeypatch.setattr(settings_repo, "set_setting", m.set)
    return m


async def test_auto_apply_routine_tick_logs_once_then_throttled(
    mem: _MemSettings, caplog: pytest.LogCaptureFixture
) -> None:
    kw = dict(
        platforms_enabled=["hh"],
        platforms_ready=["hh"],
        candidates=0,
        applied=0,
        needs_confirmation=0,
        anketa=0,
        failed=0,
        blocked=[],
        bail_reason=None,
    )
    with caplog.at_level(logging.INFO, logger="core.app.scenarios.auto_apply"):
        await aa_scenario.report_tick_summary(account_id=9, **kw)
        first = [r for r in caplog.records if "тик:" in r.getMessage()]
        assert len(first) == 1 and first[0].levelno == logging.INFO
        caplog.clear()
        await aa_scenario.report_tick_summary(account_id=9, **kw)
        assert not [r for r in caplog.records if "тик:" in r.getMessage()], "рутинный тик троттлится"

    # last_tick всё равно обновился на КАЖДОМ тике (для админ-карточки)
    entry = mem.store[(9, "auto_apply_runner_tick")]
    assert entry["at"] and entry["summary"]["candidates"] == 0  # type: ignore[index]


async def test_auto_apply_problem_tick_always_warns(
    mem: _MemSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="core.app.scenarios.auto_apply"):
        for _ in range(3):
            await aa_scenario.report_tick_summary(
                account_id=1,
                platforms_enabled=["hh"],
                platforms_ready=[],
                candidates=0,
                applied=0,
                needs_confirmation=0,
                anketa=0,
                failed=0,
                blocked=[],
                bail_reason="preview_http_502:hh",
            )
    warns = [r for r in caplog.records if "тик:" in r.getMessage()]
    assert len(warns) == 3, "проблемный тик логируется всегда, минуя троттл"
    assert all(r.levelno == logging.WARNING for r in warns)
    assert "отказ=preview_http_502:hh" in warns[0].getMessage()


async def test_auto_apply_activity_tick_logs_info_not_throttled(
    mem: _MemSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="core.app.scenarios.auto_apply"):
        for _ in range(2):
            await aa_scenario.report_tick_summary(
                account_id=2,
                platforms_enabled=["hh"],
                platforms_ready=["hh"],
                candidates=5,
                applied=1,
                needs_confirmation=0,
                anketa=0,
                failed=0,
                blocked=[],
                bail_reason=None,
            )
    logged = [r for r in caplog.records if "тик:" in r.getMessage()]
    assert len(logged) == 2, "тик с реальной отправкой не троттлится"
    assert all(r.levelno == logging.INFO for r in logged)


async def test_discovery_tick_summary_warns_on_pause(
    mem: _MemSettings, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="core.domains.opportunities.discovery_session"):
        await disc.report_tick_summary(
            account_id=7,
            platforms_running=["hh"],
            opened=3,
            scored=2,
            already_known=1,
            parse_errors=0,
            paused=["hh:suspected_block"],
            bail_reason=None,
        )
    rec = [r for r in caplog.records if "тик:" in r.getMessage()]
    assert len(rec) == 1 and rec[0].levelno == logging.WARNING
    assert "пауза=hh:suspected_block" in rec[0].getMessage()
    assert mem.store[(7, "discovery_runner_tick")]["summary"]["opened"] == 3  # type: ignore[index]


async def test_http_log_level_quiet_for_tick_report() -> None:
    from api.main import _http_log_level

    assert _http_log_level(
        method="POST", status=204, duration_ms=5, path="/api/pipeline/auto-apply/tick-report"
    ) == logging.DEBUG
    # но ошибка heartbeat-ручки по-прежнему видна
    assert _http_log_level(
        method="POST", status=500, duration_ms=5, path="/api/pipeline/auto-apply/tick-report"
    ) == logging.ERROR
    # обычная мутация не затронута
    assert _http_log_level(
        method="POST", status=200, duration_ms=5, path="/api/pipeline/auto-apply/report"
    ) == logging.INFO
