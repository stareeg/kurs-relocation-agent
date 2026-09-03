"""D-03: история произвольной величины «Рынка» поверх market_snapshots.

`GET /api/market/history?metric=...` обобщает `offer-chance-history` на любой ключ снимка:
headline-KPI из `payload["metrics"]` (например `hr_response`) и агрегаты верхнего уровня
(`offer_chance_score`).
"""

from __future__ import annotations

from datetime import date

from core.domains.market.market_snapshot import (
    MarketSnapshot,
    history_from_snapshots,
    metric_history_from_snapshots,
)


def test_kpi_metric_read_from_metrics_block() -> None:
    """Метрика из KPI-стены лежит под `payload["metrics"][key]`, не на верхнем уровне."""
    snaps = [
        MarketSnapshot(day=date(2026, 7, 29), payload={"metrics": {"hr_response": 12.0}}),
        MarketSnapshot(day=date(2026, 7, 30), payload={"metrics": {"hr_response": 18.0}}),
    ]
    history = metric_history_from_snapshots(snaps, "hr_response")
    assert history.metric == "hr_response"
    assert history.available is True
    assert [p.value for p in history.points] == [12.0, 18.0]


def test_top_level_metric_still_resolves() -> None:
    """Агрегаты верхнего уровня (`offer_chance_score`) резолвятся тем же путём."""
    snaps = [
        MarketSnapshot(day=date(2026, 7, 29), payload={"offer_chance_score": 28}),
        MarketSnapshot(day=date(2026, 7, 30), payload={"offer_chance_score": 42}),
    ]
    history = metric_history_from_snapshots(snaps, "offer_chance_score")
    assert history.available is True
    assert [p.value for p in history.points] == [28.0, 42.0]


def test_missing_metric_skipped_not_zero() -> None:
    snaps = [
        MarketSnapshot(day=date(2026, 7, 28), payload={"metrics": {"hr_response": 10.0}}),
        MarketSnapshot(day=date(2026, 7, 29), payload={"metrics": {}}),  # снимок без этой метрики
        MarketSnapshot(day=date(2026, 7, 30), payload={"metrics": {"hr_response": 20.0}}),
    ]
    history = metric_history_from_snapshots(snaps, "hr_response")
    assert [p.day for p in history.points] == [date(2026, 7, 28), date(2026, 7, 30)]
    assert history.available is True


def test_unknown_metric_key_is_empty_not_error() -> None:
    snaps = [MarketSnapshot(day=date(2026, 7, 30), payload={"metrics": {"hr_response": 10.0}})]
    history = metric_history_from_snapshots(snaps, "does_not_exist")
    assert history.points == []
    assert history.available is False


def test_offer_chance_history_matches_generic_wrapper() -> None:
    """`history_from_snapshots` — частный случай `metric_history_from_snapshots`."""
    snaps = [
        MarketSnapshot(day=date(2026, 7, 29), payload={"offer_chance_score": 28}),
        MarketSnapshot(day=date(2026, 7, 30), payload={"offer_chance_score": 42}),
    ]
    generic = metric_history_from_snapshots(snaps, "offer_chance_score")
    offer_chance = history_from_snapshots(snaps)
    assert [p.score for p in offer_chance.points] == [p.value for p in generic.points]
    assert offer_chance.available == generic.available
