"""L-26: инкрементальный пересчёт снапшотов «Рынка» — считаем только реально изменившееся.

Три вещи, ради которых шаг вводился:
1. дирти-трекер (`snapshot_dirty.py`) стартует «всё грязное» и корректно снимает/ставит грязь;
2. предохранитель форсирует пересчёт даже без событий (мутации вне шины — skip, resume_stats);
3. `_refresh_market_snapshots` реально считает только грязные срезы и продлевает чистые, не трогая
   их payload — то есть результат чистых срезов совпадает с их последним полным пересчётом.
"""

from __future__ import annotations

import pytest

from core.domains.market import snapshot_dirty as dirty


@pytest.fixture(autouse=True)
def _reset_dirty():
    dirty.reset()
    yield
    dirty.reset()


# --------------------------------------------------------------------------- snapshot_dirty


def test_starts_all_dirty():
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(dirty.ALL_KINDS)


def test_mark_computed_clears_dirty():
    dirty.mark_computed(*dirty.ALL_KINDS)
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset()


def test_mark_dirty_after_clean_recomputes_only_affected():
    dirty.mark_computed(*dirty.ALL_KINDS)
    dirty.mark_dirty(dirty.GRID)
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset({dirty.GRID})


def test_safety_net_forces_recompute_even_when_clean():
    """Мутации мимо шины (skip, resume_stats) не должны протухать тихо — см. docstring модуля."""
    dirty.mark_computed(*dirty.ALL_KINDS)
    # -1, а не 0: на быстрой машине (Windows) elapsed между двумя now() может округлиться в 0.0,
    # что делает `> 0` ложным и тест — флаковым.
    assert dirty.kinds_to_recompute(safety_net_sec=-1) == frozenset(dirty.ALL_KINDS)


def test_reset_returns_to_all_dirty():
    dirty.mark_computed(*dirty.ALL_KINDS)
    dirty.reset()
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(dirty.ALL_KINDS)


# --------------------------------------------------------------------------- events.py → dirty


def test_vacancy_scored_dirties_grid_pulse_and_search():
    from core.domains.market import events as market_events
    from core.kernel.events import VacancyScored

    dirty.mark_computed(*dirty.ALL_KINDS)
    market_events.on_vacancy_scored(VacancyScored(vacancy_id="v1"))
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(dirty.ALL_KINDS)


def test_stage_changed_dirties_grid_pulse_and_search():
    from core.domains.market import events as market_events
    from core.kernel.events import ApplicationStageChanged

    dirty.mark_computed(*dirty.ALL_KINDS)
    market_events.on_application_stage_changed(ApplicationStageChanged(vacancy_id="v1"))
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(
        {dirty.GRID, dirty.PULSE, dirty.SEARCH}
    )


def test_offer_received_dirties_grid_pulse_and_search():
    from core.domains.market import events as market_events
    from core.kernel.events import OfferReceived

    dirty.mark_computed(*dirty.ALL_KINDS)
    market_events.on_offer_received(OfferReceived(vacancy_id="v1"))
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(
        {dirty.GRID, dirty.PULSE, dirty.SEARCH}
    )


def test_hr_message_received_dirties_grid_pulse_and_search():
    from core.domains.market import events as market_events
    from core.kernel.events import HrMessageReceived

    dirty.mark_computed(*dirty.ALL_KINDS)
    market_events.on_hr_message_received(HrMessageReceived(vacancy_id="v1"))
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(
        {dirty.GRID, dirty.PULSE, dirty.SEARCH}
    )


def test_resume_updated_dirties_grid_and_pulse_only():
    from core.domains.market import events as market_events
    from core.kernel.events import ResumeUpdated

    dirty.mark_computed(*dirty.ALL_KINDS)
    market_events.on_resume_updated(ResumeUpdated())
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset(
        {dirty.GRID, dirty.PULSE}
    )


def test_market_declares_the_new_subscriptions():
    from core.domains.market.events import SUBSCRIPTIONS

    subscribed_types = {t for t, _ in SUBSCRIPTIONS}
    assert dirty.ALL_KINDS  # sanity: домен реально что-то отслеживает
    assert len(subscribed_types) == len(SUBSCRIPTIONS)  # не задвоено


# --------------------------------------------------------------------------- _refresh_market_snapshots


@pytest.fixture
def runtime():
    from core.platform.tasks import MemoryTaskStore, reset_runtime_for_tests

    return reset_runtime_for_tests(MemoryTaskStore())


async def test_refresh_recomputes_only_dirty_kind_and_touches_the_rest(
    runtime, monkeypatch: pytest.MonkeyPatch
):
    from core.domains.market import snapshot_refresh as mod

    calls: dict[str, list] = {
        "pulse": [],
        "grid": [],
        "search": [],
        "save": [],
        "touch": [],
        "daily": [],
    }

    async def _fake_pulse(**_kw):
        from core.domains.market.pulse import MarketPulse

        calls["pulse"].append(1)
        return MarketPulse(available=False)

    async def _fake_grid(**_kw):
        from core.domains.market.market_grid import MarketGrid

        calls["grid"].append(1)
        return MarketGrid(available=True)

    async def _fake_search(**_kw):
        from core.domains.market.search_metrics import SearchMetrics

        calls["search"].append(1)
        return SearchMetrics(available=True)

    async def _fake_save_snapshot(kind, *_a, **_kw):
        calls["save"].append(kind)

    async def _fake_touch_snapshot(kind, *_a, **_kw):
        calls["touch"].append(kind)

    async def _fake_record_daily(*_a, **_kw):
        calls["daily"].append(1)

    monkeypatch.setattr("core.domains.market.pulse.get_market_pulse", _fake_pulse)
    monkeypatch.setattr("core.domains.market.market_grid.get_market_grid", _fake_grid)
    monkeypatch.setattr(
        "core.domains.market.search_metrics.get_search_metrics", _fake_search
    )
    monkeypatch.setattr("core.domains.market.analytics_cache.save_snapshot", _fake_save_snapshot)
    monkeypatch.setattr(
        "core.domains.market.analytics_cache.touch_snapshot", _fake_touch_snapshot
    )
    monkeypatch.setattr(
        "core.domains.market.market_snapshot.record_daily_pulse_state", _fake_record_daily
    )

    async def _fake_owner_id(**_kw):
        return 1

    monkeypatch.setattr("core.platform.repo.accounts.resolve_default_account_id", _fake_owner_id)

    dirty.mark_computed(*dirty.ALL_KINDS)  # чистый старт — предыдущий тик всё посчитал
    dirty.mark_dirty(dirty.GRID)  # новая вакансия/стадия затронула только grid

    await mod._refresh_market_snapshots({})

    assert calls["grid"] == [1]
    assert calls["pulse"] == []  # не грязный — не пересчитан
    assert calls["search"] == []
    assert calls["save"] == ["grid"]
    assert sorted(calls["touch"]) == sorted([dirty.PULSE, dirty.SEARCH])  # payload не тронут
    assert calls["daily"] == []  # pulse не пересчитывался — нечего класть в дневной снимок
    assert dirty.kinds_to_recompute(safety_net_sec=1_000_000) == frozenset()  # grid снят с грязи


async def test_refresh_skips_everything_when_nothing_dirty(runtime, monkeypatch: pytest.MonkeyPatch):
    from core.domains.market import snapshot_refresh as mod

    heavy_calls: list[str] = []
    touched: list[str] = []

    async def _fail(*_a, **_kw):  # pragma: no cover — не должен звонить вовсе
        heavy_calls.append("called")
        raise AssertionError("тяжёлый пересчёт не должен звонить на чистом тике")

    async def _fake_touch_snapshot(kind, *_a, **_kw):
        touched.append(kind)

    monkeypatch.setattr("core.domains.market.pulse.get_market_pulse", _fail)
    monkeypatch.setattr("core.domains.market.market_grid.get_market_grid", _fail)
    monkeypatch.setattr("core.domains.market.search_metrics.get_search_metrics", _fail)
    monkeypatch.setattr(
        "core.domains.market.analytics_cache.touch_snapshot", _fake_touch_snapshot
    )

    async def _fake_owner_id(**_kw):
        return 1

    monkeypatch.setattr("core.platform.repo.accounts.resolve_default_account_id", _fake_owner_id)

    dirty.mark_computed(*dirty.ALL_KINDS)  # всё только что посчитано, предохранитель не истёк

    await mod._refresh_market_snapshots({})

    assert heavy_calls == []
    assert sorted(touched) == sorted(dirty.ALL_KINDS)
