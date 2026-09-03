"""Отчёт раннера (2.1/2.2/8.2): dry-run только логирует, реальная отправка двигает стадию
воронки через Channel-паттерн (A-27) с меткой auto_apply_<platform>. Блокеры площадки
(captcha/resume_hidden/platform_limit, Фаза 8.2) не двигают воронку вовсе — либо останавливают
площадку автоматически, либо тихо ждут до завтра."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.app import channels
from core.app.scenarios import auto_apply as scenario
from core.domains.opportunities.jobs import Job
from core.domains.pipeline.auto_apply.config import AutoApplyConfig, AutoApplyPlatformConfig
from core.kernel.schemas.funnel import FunnelStatus


def _job(status: str) -> Job:
    return Job(vacancy_id="1", vacancy_text="x" * 60, status=status)


async def test_dry_run_never_moves_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", mock)

    result = await scenario.report_attempt(
        "hh", job_id=1, vacancy_id="1", dry_run=True, account_id=9
    )

    assert result is None
    mock.assert_not_called()


async def test_real_apply_moves_stage_with_platform_source(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(return_value=_job(FunnelStatus.APPLIED.value))
    monkeypatch.setattr(scenario, "set_stage_via", mock)

    result = await scenario.report_attempt(
        "getmatch", job_id=42, vacancy_id="v42", dry_run=False, account_id=9
    )

    assert result is not None
    assert result.status == FunnelStatus.APPLIED.value
    mock.assert_awaited_once_with(
        channels.AUTO_APPLY_GETMATCH, 42, FunnelStatus.APPLIED.value, account_id=9
    )


async def test_real_apply_warns_when_faster_than_two_per_minute(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Жёсткий потолок держит раннер (`awaitRealApplySlot` + серверный клок); если два реальных
    отклика площадки пришли в зазоре 45–90с — мягкий WARNING (перезапуск SW обнулил локальный
    клок, первый отклик ушёл сразу — норма), площадку не трогаем."""
    import logging
    from datetime import UTC, datetime, timedelta

    monkeypatch.setattr(scenario, "set_stage_via", AsyncMock(return_value=_job("Отклик")))
    monkeypatch.setattr(
        scenario,
        "last_real_apply_at",
        AsyncMock(return_value=datetime.now(UTC) - timedelta(seconds=60)),
    )
    rec_mock = AsyncMock()
    monkeypatch.setattr(scenario, "record_real_apply", rec_mock)
    disable_mock = AsyncMock()
    monkeypatch.setattr(scenario, "disable_platform", disable_mock)

    with caplog.at_level(logging.WARNING, logger="core.app.scenarios.auto_apply"):
        await scenario.report_attempt("hh", job_id=1, vacancy_id="1", dry_run=False, account_id=9)

    assert any("чаще 1 раз в 2 мин" in r.message for r in caplog.records)
    disable_mock.assert_not_awaited()
    rec_mock.assert_awaited_once_with("hh", account_id=9)


async def test_real_apply_breaker_disables_platform_when_blatantly_faster(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Два реальных отклика площадки ближе `_THROTTLE_BREAKER_S` — раннер обойдён (двойной клик /
    модифицированный раннер): площадка выключается автоматически, один отклик проскочил, залп
    не пройдёт. Стадию воронки первому всё равно двигаем — клик-то был."""
    import logging
    from datetime import UTC, datetime, timedelta

    stage_mock = AsyncMock(return_value=_job("Отклик"))
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)
    monkeypatch.setattr(
        scenario,
        "last_real_apply_at",
        AsyncMock(return_value=datetime.now(UTC) - timedelta(seconds=8)),
    )
    monkeypatch.setattr(scenario, "record_real_apply", AsyncMock())
    disable_mock = AsyncMock()
    monkeypatch.setattr(scenario, "disable_platform", disable_mock)

    with caplog.at_level(logging.ERROR, logger="core.app.scenarios.auto_apply"):
        await scenario.report_attempt("hh", job_id=1, vacancy_id="1", dry_run=False, account_id=9)

    disable_mock.assert_awaited_once_with("hh", account_id=9)
    assert any("троттлинг обойдён" in r.message for r in caplog.records)
    stage_mock.assert_awaited_once()


async def test_each_platform_maps_to_its_own_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(return_value=_job(FunnelStatus.APPLIED.value))
    monkeypatch.setattr(scenario, "set_stage_via", mock)

    await scenario.report_attempt("hh", job_id=1, vacancy_id="1", dry_run=False, account_id=1)
    await scenario.report_attempt("habr", job_id=2, vacancy_id="2", dry_run=False, account_id=1)

    used_channels = [call.args[0] for call in mock.await_args_list]
    assert used_channels == [channels.AUTO_APPLY_HH, channels.AUTO_APPLY_HABR]


@pytest.mark.parametrize("outcome", ["captcha", "resume_hidden"])
async def test_blocker_outcome_disables_only_that_platform_and_never_moves_stage(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    stage_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)
    current = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=True, daily_cap=10),
        getmatch=AutoApplyPlatformConfig(enabled=True),
    )
    get_mock = AsyncMock(return_value=current)
    set_mock = AsyncMock()
    monkeypatch.setattr(scenario, "get_auto_apply_config", get_mock)
    monkeypatch.setattr(scenario, "set_auto_apply_config", set_mock)

    result = await scenario.report_attempt(
        "hh", job_id=1, vacancy_id="1", dry_run=False, account_id=9, outcome=outcome
    )

    assert result is None
    stage_mock.assert_not_called()
    set_mock.assert_awaited_once()
    saved: AutoApplyConfig = set_mock.await_args.args[0]
    assert saved.hh.enabled is False
    assert saved.hh.daily_cap == 10, "остальные настройки площадки не тронуты"
    assert saved.getmatch.enabled is True, "соседняя площадка не тронута"


async def test_platform_limit_outcome_marks_runtime_state_not_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)
    mark_mock = AsyncMock()
    monkeypatch.setattr(scenario, "mark_platform_limit", mark_mock)

    result = await scenario.report_attempt(
        "hh", job_id=1, vacancy_id="1", dry_run=False, account_id=9, outcome="platform_limit"
    )

    assert result is None
    stage_mock.assert_not_called()
    mark_mock.assert_awaited_once_with("hh", account_id=9)


async def test_unknown_outcome_falls_back_to_normal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(return_value=_job(FunnelStatus.APPLIED.value))
    monkeypatch.setattr(scenario, "set_stage_via", mock)

    result = await scenario.report_attempt(
        "hh", job_id=1, vacancy_id="1", dry_run=False, account_id=9, outcome="applied"
    )

    assert result is not None
    mock.assert_awaited_once()


async def test_failure_outcome_moves_to_manual_review_with_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Боевой режим + timeout/no_button/… — в «Ручной разбор» с русским пояснением, не в воронку."""
    stage_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)
    override_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_override", override_mock)
    # `timeout` — исход «не дождались подтверждения», сценарий сверяется со стадией воронки
    # (см. тесты ниже); здесь отклика в воронке нет, поэтому поведение прежнее.
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=_job(FunnelStatus.VIEWED.value)))

    result = await scenario.report_attempt(
        "hh",
        job_id=720,
        vacancy_id="136147280",
        dry_run=False,
        account_id=9,
        outcome="timeout",
    )

    assert result is None
    stage_mock.assert_not_called()
    override_mock.assert_awaited_once()
    assert override_mock.await_args.args[:2] == (720, "manual_review")
    assert "долго" in (override_mock.await_args.kwargs.get("reason") or "")


async def test_failure_outcome_in_dry_run_does_not_move_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stage_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)
    override_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_override", override_mock)

    result = await scenario.report_attempt(
        "hh", job_id=1, vacancy_id="1", dry_run=True, account_id=9, outcome="timeout"
    )

    assert result is None
    stage_mock.assert_not_called()
    override_mock.assert_not_called()


async def test_needs_confirmation_parks_letter_only_no_llm_no_stage_move(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Фаза 3.4: режим «Тест» без анкеты — паркуем pending с пустыми questions/answers, не
    зовём генерацию (письмо уже отдельно в jobs.cover_letter_text) и не двигаем воронку."""
    stage_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)
    update_mock = AsyncMock(return_value=_job(FunnelStatus.VIEWED.value))
    monkeypatch.setattr(scenario, "update_job_anketa", update_mock)
    generate_mock = AsyncMock()
    monkeypatch.setattr(scenario, "generate_anketa_answers", generate_mock)

    result = await scenario.report_attempt(
        "hh", job_id=7, vacancy_id="v7", dry_run=False, account_id=9, outcome="needs_confirmation"
    )

    assert result is None
    stage_mock.assert_not_called()
    generate_mock.assert_not_called()
    update_mock.assert_awaited_once()
    call = update_mock.await_args
    assert call.args[0] == "v7"
    parked = call.kwargs["anketa"]
    assert parked["status"] == "pending"
    assert parked["platform"] == "hh"
    assert parked["questions"] == []
    assert parked["answers"] == []


async def test_disable_platform_leaves_neighbors_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    current = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=True),
        getmatch=AutoApplyPlatformConfig(enabled=True, daily_cap=7),
        habr=AutoApplyPlatformConfig(enabled=False),
    )
    monkeypatch.setattr(scenario, "get_auto_apply_config", AsyncMock(return_value=current))
    set_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_auto_apply_config", set_mock)

    result = await scenario.disable_platform("getmatch", account_id=3)

    assert result.getmatch.enabled is False
    assert result.getmatch.daily_cap == 7
    assert result.hh.enabled is True
    set_mock.assert_awaited_once_with(result, account_id=3)


# ── «Не смогли подтвердить» ≠ «не отправили» (прод 2026-08-31, job 867) ──────────────────────
# hh.ru показал свою модалку («в каком городе ищете работу») поверх страницы сразу после клика,
# маркеры «Резюме доставлено» под ней не проявились за `apply_confirm_timeout_ms` — раннер
# отрапортовал `error`. Отклик при этом УШЁЛ: контент-скрипт заметил это своим путём и записал
# стадию `Отклик` (`api_funnel`) за секунду до репорта. Вакансия всё равно уехала в «Ручной
# разбор» с надписью «Сбой при отправке отклика» — владелец увидел бы её как несделанную работу.


@pytest.mark.parametrize("outcome", ["error", "timeout"])
async def test_unconfirmed_outcome_trusts_funnel_stage(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    override_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_override", override_mock)
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=_job(FunnelStatus.APPLIED.value)))
    record_mock = AsyncMock()
    monkeypatch.setattr(scenario, "record_real_apply", record_mock)
    stage_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_stage_via", stage_mock)

    result = await scenario.report_attempt(
        "hh", job_id=867, vacancy_id="136629732", dry_run=False, account_id=1, outcome=outcome
    )

    assert result is not None, "отклик в воронке — попытка засчитана, а не потеряна"
    override_mock.assert_not_called(), "вакансия не должна ехать в «Ручной разбор»"
    record_mock.assert_awaited_once()
    # Стадию повторно не двигаем — она уже `Отклик`, её выставил контент-скрипт.
    stage_mock.assert_not_called()


@pytest.mark.parametrize("outcome", ["error", "timeout"])
async def test_unconfirmed_outcome_without_funnel_stage_goes_to_manual(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """Нет подтверждения И нет отклика в воронке — прежнее поведение, ручной разбор."""
    override_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_override", override_mock)
    monkeypatch.setattr(scenario, "get_job", AsyncMock(return_value=_job(FunnelStatus.VIEWED.value)))
    monkeypatch.setattr(scenario, "record_real_apply", AsyncMock())
    monkeypatch.setattr(scenario, "set_stage_via", AsyncMock())

    result = await scenario.report_attempt(
        "hh", job_id=5, vacancy_id="5", dry_run=False, account_id=1, outcome=outcome
    )

    assert result is None
    override_mock.assert_awaited_once()
    assert override_mock.await_args.args[1] == "manual_review"


async def test_hard_failure_ignores_funnel_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    """`no_button` — не «не дождались подтверждения», а «кликать было нечего»: сверка со
    стадией сюда не относится, иначе любой сбой на уже откликнутой вакансии сойдёт за успех."""
    override_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_override", override_mock)
    get_mock = AsyncMock(return_value=_job(FunnelStatus.APPLIED.value))
    monkeypatch.setattr(scenario, "get_job", get_mock)
    monkeypatch.setattr(scenario, "set_stage_via", AsyncMock())

    result = await scenario.report_attempt(
        "hh", job_id=6, vacancy_id="6", dry_run=False, account_id=1, outcome="no_button"
    )

    assert result is None
    override_mock.assert_awaited_once()
    get_mock.assert_not_called()


async def test_dry_run_unconfirmed_stays_a_log(monkeypatch: pytest.MonkeyPatch) -> None:
    """Площадка в режиме проверки: сверять с воронкой нечего, реального клика не было."""
    override_mock = AsyncMock()
    monkeypatch.setattr(scenario, "set_override", override_mock)
    get_mock = AsyncMock(return_value=_job(FunnelStatus.APPLIED.value))
    monkeypatch.setattr(scenario, "get_job", get_mock)
    monkeypatch.setattr(scenario, "set_stage_via", AsyncMock())

    result = await scenario.report_attempt(
        "hh", job_id=7, vacancy_id="7", dry_run=True, account_id=1, outcome="error"
    )

    assert result is None
    override_mock.assert_not_called()
    get_mock.assert_not_called()
