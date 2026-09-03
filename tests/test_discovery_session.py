"""Discovery (авто-открытие вакансий): конфиг, состояние сессии, тик решений."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities import discovery_session as ds
from core.domains.opportunities.jobs import Job
from core.domains.pipeline.auto_apply.queue import AutoApplyQueuePreview
from core.kernel.errors import InvalidInput


@pytest.fixture
def settings_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    store: dict[str, Any] = {}

    async def fake_get(
        key: str, default: Any = None, *, account_id: Any = None, db: Any = None
    ) -> Any:
        _ = account_id, db
        return store.get(key, default)

    async def fake_set(key: str, value: Any, *, account_id: Any = None, db: Any = None) -> None:
        _ = account_id, db
        store[key] = value

    monkeypatch.setattr(ds, "get_setting", fake_get)
    monkeypatch.setattr(ds, "set_setting", fake_set)
    # Правка 2026-08-20: `get_discovery_status` теперь всегда подмешивает живой статус/пропуск
    # (`_attach_live_job_state`) — дефолт «ничего не нашли», тесты, которым нужен конкретный
    # job_status/job_skipped, переопределяют эти два мока сами после вызова фикстуры.
    monkeypatch.setattr(ds, "get_jobs_by_vacancy_ids", AsyncMock(return_value={}))
    monkeypatch.setattr(ds, "get_skipped_ids", AsyncMock(return_value=set()))
    return store


# --- Конфиг ---


async def test_default_config_disabled(settings_store: dict[str, Any]) -> None:
    config = await ds.get_discovery_config(account_id=1)
    assert config.hh.enabled is False
    assert config.getmatch.enabled is False
    # 2026-08-28: строго последовательный просмотр — 1 вакансия за тик.
    assert config.hh.batch_size == 1


async def test_config_round_trip(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    config.hh.daily_cap = 30
    await ds.set_discovery_config(config, account_id=1)

    loaded = await ds.get_discovery_config(account_id=1)
    assert loaded.hh.enabled is True
    assert loaded.hh.search_urls == ["https://hh.ru/search/vacancy?text=python"]
    assert loaded.hh.daily_cap == 30
    assert loaded.getmatch.enabled is False


async def test_garbage_config_falls_back_to_defaults(settings_store: dict[str, Any]) -> None:
    settings_store[ds.KEY_DISCOVERY_CONFIG] = "not-a-dict"
    config = await ds.get_discovery_config(account_id=1)
    assert config == ds.DiscoveryConfig()


# Этап 5 редизайна «Расширения» — старый одиночный `search_url` конвертируется в `search_urls`
# при чтении, без отдельной SQL-миграции (app_settings — jsonb).


def test_migrates_legacy_single_search_url() -> None:
    config = ds.discovery_config_from_mapping(
        {"hh": {"enabled": True, "search_url": "https://hh.ru/search/vacancy?text=python"}}
    )
    assert config.hh.search_urls == ["https://hh.ru/search/vacancy?text=python"]


def test_legacy_search_url_does_not_override_existing_search_urls() -> None:
    config = ds.discovery_config_from_mapping(
        {
            "hh": {
                "enabled": True,
                "search_url": "https://hh.ru/search/vacancy?text=old",
                "search_urls": ["https://hh.ru/search/vacancy?text=new"],
            }
        }
    )
    assert config.hh.search_urls == ["https://hh.ru/search/vacancy?text=new"]


def test_no_legacy_search_url_leaves_search_urls_empty() -> None:
    config = ds.discovery_config_from_mapping({"hh": {"enabled": True}})
    assert config.hh.search_urls == []


# --- Сессия: старт/пауза/резюме/стоп ---


async def test_start_with_no_config_raises_missing_search_url(
    settings_store: dict[str, Any],
) -> None:
    """Совсем пустой конфиг (свежий аккаунт) — падает из-за отсутствия search-URL, не из-за
    выключенной площадки (см. `test_start_self_heals_disabled_platform_with_search_url` ниже:
    сам по себе `enabled=False` больше не блокирует старт)."""
    with pytest.raises(InvalidInput):
        await ds.start_session("hh", account_id=1)


async def test_start_self_heals_disabled_platform_with_search_url(
    settings_store: dict[str, Any],
) -> None:
    """Инцидент 2026-08-19: переключатель «Просмотр/Отклик» во фронте по умолчанию показывает
    вкладку «Просмотр» ещё до того, как реально шлёт PATCH `enabled=true` (см. computeMode в
    PlatformPipelineSection.tsx) — владелец жал «Начать» на уже видимой вкладке с сохранённым
    search-URL и получал загадочный отказ «discovery выключен в настройках». Явный клик «Начать»
    — однозначное намерение запустить именно эту площадку: старт включает её сам, а не требует
    отдельного шага, который фронт не всегда успевает сделать."""
    config = ds.DiscoveryConfig()
    config.hh.enabled = False
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)

    status = await ds.start_session("hh", account_id=1)

    assert status.state == "running"
    healed = await ds.get_discovery_config(account_id=1)
    assert healed.hh.enabled is True
    # Соседние площадки не трогает — self-heal не должен задеть getmatch/habr.
    assert healed.getmatch.enabled is False


async def test_start_requires_search_url(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    await ds.set_discovery_config(config, account_id=1)
    with pytest.raises(InvalidInput):
        await ds.start_session("hh", account_id=1)


async def test_start_requires_search_url_ignores_blank_entries(
    settings_store: dict[str, Any],
) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["  ", ""]
    await ds.set_discovery_config(config, account_id=1)
    with pytest.raises(InvalidInput):
        await ds.start_session("hh", account_id=1)


async def test_start_accepts_multiple_search_urls(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = [
        "https://hh.ru/search/vacancy?text=python",
        "https://hh.ru/search/vacancy?text=backend",
    ]
    await ds.set_discovery_config(config, account_id=1)
    status = await ds.start_session("hh", account_id=1)
    assert status.state == "running"


async def test_start_sets_running_with_fresh_counters(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)

    status = await ds.start_session("hh", account_id=1)
    assert status.state == "running"
    assert status.opened == 0
    assert status.session_started_at is not None


async def test_pause_reason_maps_to_state(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)
    await ds.start_session("hh", account_id=1)

    status = await ds.pause_session("hh", account_id=1, reason="daily_cap")
    assert status.state == "paused_daily_cap"

    status = await ds.pause_session("hh", account_id=1, reason="suspected_block")
    assert status.state == "paused_suspected_block"


async def test_resume_requires_started_session(settings_store: dict[str, Any]) -> None:
    with pytest.raises(InvalidInput):
        await ds.resume_session("hh", account_id=1)


async def test_pause_then_resume(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.getmatch.enabled = True
    config.getmatch.search_urls = ["https://getmatch.ru/vacancies"]
    await ds.set_discovery_config(config, account_id=1)
    await ds.start_session("getmatch", account_id=1)

    await ds.pause_session("getmatch", account_id=1, reason="user")
    status = await ds.resume_session("getmatch", account_id=1)
    assert status.state == "running"


async def test_stop_resets_to_idle(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)
    await ds.start_session("hh", account_id=1)

    status = await ds.stop_session("hh", account_id=1)
    assert status.state == "idle"


async def test_platforms_are_independent(settings_store: dict[str, Any]) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)
    await ds.start_session("hh", account_id=1)

    getmatch_status = await ds.get_discovery_status("getmatch", account_id=1)
    assert getmatch_status.state == "idle"


# --- Тик ---


def _job(vacancy_id: str, overall_score: int | None) -> Job:
    return Job(vacancy_id=vacancy_id, vacancy_text="x" * 2000, overall_score=overall_score)


async def test_tick_already_known_job_not_found(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="already_known")
    assert status.opened == 1
    assert status.already_known == 1
    assert status.events[0].label == "уже в системе — пропущено"
    assert status.events[0].overall_score is None
    assert status.events[0].job_id is None


# Правка 2026-08-19 (баг 3): «уже в системе» раньше никогда не подтягивала свой скор/job_id —
# строка лога навсегда оставалась без балла и без квик-экшенов (job_id нужен фронту, чтобы их
# показать). Тик теперь смотрит текущую запись вакансии и подтягивает то, что уже есть.
async def test_tick_already_known_populates_score_and_job_id(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job("1", overall_score=62)
    job.id = 606
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="already_known")
    assert status.events[0].overall_score == 62
    assert status.events[0].job_id == 606
    assert status.events[0].label == "62 баллов — уже в системе"


# Правка 2026-08-20: `get_discovery_status` подмешивает АКТУАЛЬНЫЙ статус воронки/пропуск в уже
# записанное событие «уже в системе» — иначе фронт показывал бы кнопки решения поверх вакансии,
# которая с момента тика успела продвинуться по воронке или была пропущена.
async def test_status_attaches_live_job_state_for_already_known(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job("1", overall_score=62)
    job.id = 606
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="already_known")

    advanced_job = _job("1", overall_score=62)
    advanced_job.id = 606
    advanced_job.status = "Скрининг"
    monkeypatch.setattr(ds, "get_jobs_by_vacancy_ids", AsyncMock(return_value={"1": advanced_job}))
    status = await ds.get_discovery_status("hh", account_id=1)
    assert status.events[0].job_status == "Скрининг"
    assert status.events[0].job_skipped is False


async def test_status_attaches_live_skip_flag(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job("1", overall_score=62)
    job.id = 606
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="already_known")

    monkeypatch.setattr(ds, "get_jobs_by_vacancy_ids", AsyncMock(return_value={"1": job}))
    monkeypatch.setattr(ds, "get_skipped_ids", AsyncMock(return_value={"1"}))
    status = await ds.get_discovery_status("hh", account_id=1)
    assert status.events[0].job_skipped is True


async def test_tick_parse_error(settings_store: dict[str, Any]) -> None:
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="parse_error")
    assert status.parse_error == 1
    assert "не удалось прочитать" in status.events[0].label


async def test_tick_scored_queued_auto(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job("1", overall_score=90)
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    monkeypatch.setattr(
        ds,
        "preview_queue",
        AsyncMock(
            return_value=AutoApplyQueuePreview(
                platform="hh",
                enabled=True,
                auto=[job],
                manual_review=[],
                applied=[],
                failure_reasons={},
            )
        ),
    )
    status = await ds.report_tick(
        "hh", account_id=1, vacancy_id="1", outcome="scored", title="Backend", company="Acme"
    )
    assert status.scored == 1
    assert status.queued_auto == 1
    assert status.events[0].label == "90 баллов → в очередь автооткликов"
    assert status.events[0].bucket == "queued_auto"
    assert status.events[0].overall_score == 90
    assert status.events[0].title == "Backend"


async def test_tick_scored_queued_manual(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job("1", overall_score=68)
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    monkeypatch.setattr(
        ds,
        "preview_queue",
        AsyncMock(
            return_value=AutoApplyQueuePreview(
                platform="hh",
                enabled=True,
                auto=[],
                manual_review=[job],
                applied=[],
                failure_reasons={},
            )
        ),
    )
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")
    assert status.queued_manual == 1
    assert status.events[0].label == "68 баллов → на ручной разбор"
    assert status.events[0].bucket == "queued_manual"


async def test_tick_scored_excluded(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job("1", overall_score=30)
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    monkeypatch.setattr(
        ds,
        "preview_queue",
        AsyncMock(
            return_value=AutoApplyQueuePreview(
                platform="hh",
                enabled=True,
                auto=[],
                manual_review=[],
                applied=[],
                failure_reasons={},
            )
        ),
    )
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")
    assert status.excluded == 1
    assert status.events[0].label == "30 баллов → пропущено"


async def test_tick_scored_without_score_is_excluded(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")
    assert status.excluded == 1
    assert status.events[0].label == "не удалось оценить — пропущено"


# --- Суточный потолок автопросмотра (2026-08-28) ---


async def test_scored_tick_bumps_calendar_day_counter(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")
    assert status.daily_used == 1
    assert status.daily_cap == ds.discovery_daily_hard_cap("hh") == 200
    status = await ds.report_tick("hh", account_id=1, vacancy_id="2", outcome="parse_error")
    assert status.daily_used == 2


async def test_already_known_does_not_count_toward_daily(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    status = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="already_known")
    assert status.daily_used == 0


async def test_daily_cap_pauses_session(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    monkeypatch.setitem(ds.DISCOVERY_DAILY_HARD_CAP, "hh", 2)
    settings_store[ds.KEY_DISCOVERY_RUNTIME] = {"hh": {"state": "running"}}

    s1 = await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")
    assert s1.state == "running"
    s2 = await ds.report_tick("hh", account_id=1, vacancy_id="2", outcome="scored")
    assert s2.state == "paused_daily_cap"
    assert s2.daily_used == 2
    assert any("Дневной лимит автопросмотра исчерпан" in e.label for e in s2.events)


async def test_start_session_blocked_when_daily_cap_exhausted(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ds.DISCOVERY_DAILY_HARD_CAP, "hh", 1)
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    settings_store[ds.KEY_DISCOVERY_RUNTIME] = {"hh": {"state": "running"}}
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")

    with pytest.raises(InvalidInput, match="дневной лимит автопросмотра"):
        await ds.start_session("hh", account_id=1)


async def test_tick_records_pages_visited(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    status = await ds.report_tick(
        "hh", account_id=1, vacancy_id="1", outcome="already_known", pages_visited=3
    )
    assert status.pages_visited == 3

    # Следующий тик без pages_visited (напр. old-версия расширения) не затирает прошлое значение.
    status = await ds.report_tick("hh", account_id=1, vacancy_id="2", outcome="already_known")
    assert status.pages_visited == 3


# Правка 2026-08-19 (баг 2): раньше 20 — лог обрезался задолго до реальной остановки раннера
# (daily_cap до 300), «Просмотрено» в шапке продолжало расти — выглядело как нерабочий лимит.
async def test_events_not_capped_at_old_limit_of_20(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    for i in range(25):
        await ds.report_tick("hh", account_id=1, vacancy_id=str(i), outcome="already_known")
    status = await ds.get_discovery_status("hh", account_id=1)
    assert status.opened == 25
    assert status.already_known == 25
    assert len(status.events) == 25
    # Последнее событие сверху (свежее — первым).
    assert status.events[0].vacancy_id == "24"


async def test_events_still_capped_at_max(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    monkeypatch.setattr(ds, "_MAX_EVENTS", 3)
    for i in range(5):
        await ds.report_tick("hh", account_id=1, vacancy_id=str(i), outcome="already_known")
    status = await ds.get_discovery_status("hh", account_id=1)
    assert status.opened == 5
    assert len(status.events) == 3
    assert status.events[0].vacancy_id == "4"


# --- Самопочинка скора (баг 5) ---


async def test_heal_stale_scores_backfills_once_job_is_scored(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Вакансия не смогла заскориться в момент тика (excluded, без балла) — владелец открыл её
    вручную, скор посчитался. Следующий запрос статуса должен сам подтянуть свежий скор в лог,
    не дожидаясь нового тика от расширения."""
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="scored")
    status = await ds.get_discovery_status("hh", account_id=1)
    assert status.events[0].overall_score is None
    assert status.events[0].label == "не удалось оценить — пропущено"

    job = _job("1", overall_score=73)
    job.id = 900
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    healed = await ds.get_discovery_status("hh", account_id=1)
    assert healed.events[0].overall_score == 73
    assert healed.events[0].job_id == 900
    assert healed.events[0].label == "73 баллов → пропущено"

    # Подтянутый скор персистится — следующий запрос статуса не обязан снова ходить в jobs.
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(side_effect=AssertionError))
    again = await ds.get_discovery_status("hh", account_id=1)
    assert again.events[0].overall_score == 73


async def test_heal_stale_scores_reclassifies_parse_errors(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Правка 2026-08-20: `parse_error` почти всегда значит «расширение сдалось ждать раньше, чем
    бэк доскорил» (job_search budget_ms=60000 против прежнего клиентского таймаута 20000мс), не
    «вакансию нельзя прочитать» — вакансия обычно ЕСТЬ в системе секундами позже. Лечение теперь
    подтягивает её и переклассифицирует событие в настоящую корзину (auto/manual/excluded), а не
    оставляет строку лога навсегда «Ошибкой чтения»."""
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="parse_error")

    job = _job("1", overall_score=90)
    job.id = 900
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=job))
    monkeypatch.setattr(
        ds,
        "preview_queue",
        AsyncMock(
            return_value=AutoApplyQueuePreview(
                platform="hh",
                enabled=True,
                auto=[job],
                manual_review=[],
                applied=[],
                failure_reasons={},
            )
        ),
    )
    healed = await ds.get_discovery_status("hh", account_id=1)

    assert healed.parse_error == 0
    assert healed.queued_auto == 1
    assert healed.events[0].bucket == "queued_auto"
    assert healed.events[0].overall_score == 90
    assert healed.events[0].job_id == 900
    assert healed.events[0].label == "90 баллов → в очередь автооткликов"
    # Вакансия была лишь медленной, не нечитаемой — слот суточного потолка вернулся.
    assert healed.daily_used == 0


async def test_consecutive_parse_errors_pause_session(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """N `parse_error` подряд = парсер/площадка сломаны — площадка встаёт на паузу, не выжигая
    весь суточный потолок битыми вкладками. Успешный скор между ними сбрасывает счётчик."""
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    settings_store[ds.KEY_DISCOVERY_RUNTIME] = {"hh": {"state": "running"}}

    for i in range(ds._PARSE_ERROR_BREAKER - 1):
        s = await ds.report_tick("hh", account_id=1, vacancy_id=str(i), outcome="parse_error")
        assert s.state == "running"
    s = await ds.report_tick("hh", account_id=1, vacancy_id="last", outcome="parse_error")
    assert s.state == "paused_suspected_block"
    assert s.consecutive_parse_errors == ds._PARSE_ERROR_BREAKER

    # Возобновление даёт честный новый заход — счётчик обнулён.
    resumed = await ds.resume_session("hh", account_id=1)
    assert resumed.consecutive_parse_errors == 0


async def test_scored_tick_resets_consecutive_parse_errors(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    settings_store[ds.KEY_DISCOVERY_RUNTIME] = {"hh": {"state": "running"}}
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="parse_error")
    await ds.report_tick("hh", account_id=1, vacancy_id="2", outcome="parse_error")
    s = await ds.report_tick("hh", account_id=1, vacancy_id="3", outcome="scored")
    assert s.consecutive_parse_errors == 0


# Правка 2026-08-19 (пост-инцидент): убран лимит в 20 событий → в реальности до 300 хвостов «не
# удалось оценить» могли копиться на проде. Без бюджета лечение уходило в БД на каждое такое
# событие на КАЖДЫЙ опрос статуса (веб дергает его раз в 2.5с, пока сессия running).
async def test_heal_stale_scores_respects_lookup_budget(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    for i in range(30):
        await ds.report_tick("hh", account_id=1, vacancy_id=str(i), outcome="scored")

    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", lookup)
    await ds.get_discovery_status("hh", account_id=1)
    assert lookup.call_count == ds._HEAL_LOOKUP_BUDGET


# Инцидент 2026-08-19 («Автопросмотр» переставал открывать вкладки): get_discovery_status()
# лечила счёт по событиям и, если что-то починила, переписывала raw[platform] ЦЕЛИКОМ со своего
# снимка НАЧАЛА функции — включая state. Статус опрашивается на этом хвосте каждые 2.5с (веб),
# пока сессия running; если за время похода в БД (лечение одного события) кто-то параллельно менял
# состояние сессии, эта запись затирала его обратно устаревшим значением. Владелец жал «Начать» —
# бэк отвечал 200, но статус тут же откатывался в idle без единой ошибки в логах, расширение
# переставало видеть running и не открывало вкладки.
async def test_heal_write_back_does_not_clobber_concurrent_state_change(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)
    await ds.start_session("hh", account_id=1)

    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    await ds.report_tick(
        "hh", account_id=1, vacancy_id="1", outcome="scored"
    )  # excluded, без балла

    job = _job("1", overall_score=73)
    job.id = 900

    async def heal_lookup_races_with_pause(*args: Any, **kwargs: Any) -> Job:
        # Пока «идёт поход в БД» внутри лечения — параллельный запрос ставит сессию на паузу.
        await ds.pause_session("hh", account_id=1, reason="user")
        return job

    monkeypatch.setattr(
        ds, "get_job_by_vacancy_id", AsyncMock(side_effect=heal_lookup_races_with_pause)
    )
    healed = await ds.get_discovery_status("hh", account_id=1)

    # Правка 2026-08-20: пауза теперь пишет свой маркер-разделитель в тот же events (пункт 8,
    # «Лимит за очередь») — он и есть events[0] (препендится), вылеченная запись вакансии — под ним.
    assert healed.events[0].bucket == "session_boundary"
    healed_event = next(e for e in healed.events if e.vacancy_id == "1")
    assert healed_event.overall_score == 73  # лечение применилось
    assert healed.state == "paused_by_user"  # но не откатило конкурентную паузу обратно в running


# --- Очистка лога (кнопка «Очистить») ---


async def test_clear_events_resets_log_but_not_session(
    settings_store: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ds.DiscoveryConfig()
    config.hh.enabled = True
    config.hh.search_urls = ["https://hh.ru/search/vacancy?text=python"]
    await ds.set_discovery_config(config, account_id=1)
    await ds.start_session("hh", account_id=1)
    monkeypatch.setattr(ds, "get_job_by_vacancy_id", AsyncMock(return_value=None))
    await ds.report_tick("hh", account_id=1, vacancy_id="1", outcome="already_known")

    status = await ds.clear_events("hh", account_id=1)
    assert status.events == []
    assert status.state == "running"
    assert status.already_known == 1
