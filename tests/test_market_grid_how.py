"""У каждой метрики сетки есть человеческий `how`, и ячейка его несёт."""

from __future__ import annotations

from core.domains.market.market_grid import GRID_METRIC_HOW, GRID_SPEC, build_market_grid
from core.domains.market.pulse import MarketPulse, OfferChance


def test_every_grid_spec_key_has_how() -> None:
    missing = [key for key, _, _ in GRID_SPEC if not (GRID_METRIC_HOW.get(key) or "").strip()]
    assert missing == [], f"нет how для ключей: {missing}"


def test_build_market_grid_fills_cell_how() -> None:
    pulse = MarketPulse(available=True, offer_chance=OfferChance(score=42))
    grid = build_market_grid(
        pulse=pulse,
        jobs=[],
        stages=[],
        skipped_rows=[],
        hr_first_inbound={},
    )
    assert grid.available is True
    assert len(grid.cells) == len(GRID_SPEC)
    for cell in grid.cells:
        assert cell.how == GRID_METRIC_HOW[cell.key]
        assert cell.how
