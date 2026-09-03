"""B-04: история шанса офферов — без интерполяции, available только при ≥2 точках.

D-03: `history_from_snapshots` — частный случай `metric_history_from_snapshots` для
`offer_chance_score`; отдельный тест на generic-сборку — `test_metric_history.py`.
"""

from __future__ import annotations

from datetime import date

from core.domains.market.market_snapshot import (
    MarketSnapshot,
    clamp_history_days,
    history_from_snapshots,
)


def test_one_point_unavailable() -> None:
    snaps = [
        MarketSnapshot(day=date(2026, 7, 30), payload={"offer_chance_score": 42}),
    ]
    history = history_from_snapshots(snaps)
    assert history.available is False
    assert len(history.points) == 1
    assert history.points[0].score == 42.0


def test_two_points_available() -> None:
    snaps = [
        MarketSnapshot(day=date(2026, 7, 29), payload={"offer_chance_score": 28}),
        MarketSnapshot(day=date(2026, 7, 30), payload={"offer_chance_score": 42}),
    ]
    history = history_from_snapshots(snaps)
    assert history.available is True
    assert [p.score for p in history.points] == [28.0, 42.0]


def test_gaps_not_interpolated() -> None:
    """День без снимка не появляется в points — разрыв остаётся разрывом."""
    snaps = [
        MarketSnapshot(day=date(2026, 7, 28), payload={"offer_chance_score": 30}),
        MarketSnapshot(day=date(2026, 7, 30), payload={"offer_chance_score": 40}),
    ]
    history = history_from_snapshots(snaps)
    assert history.available is True
    assert [p.day for p in history.points] == [date(2026, 7, 28), date(2026, 7, 30)]
    assert date(2026, 7, 29) not in {p.day for p in history.points}


def test_missing_score_skipped() -> None:
    snaps = [
        MarketSnapshot(day=date(2026, 7, 28), payload={"offer_chance_score": 30}),
        MarketSnapshot(day=date(2026, 7, 29), payload={}),  # нет score
        MarketSnapshot(day=date(2026, 7, 30), payload={"offer_chance_score": 40}),
    ]
    history = history_from_snapshots(snaps)
    assert [p.day for p in history.points] == [date(2026, 7, 28), date(2026, 7, 30)]
    assert history.available is True


def test_clamp_history_days() -> None:
    assert clamp_history_days(1) == 7
    assert clamp_history_days(30) == 30
    assert clamp_history_days(999) == 180
