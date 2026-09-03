"""D-06: распределение вилок + зона цели — `compute_market_supply`, чистая функция."""

from __future__ import annotations

from datetime import UTC, datetime

from core.domains.market.market_supply import compute_market_supply

_NOW = datetime(2026, 8, 1, tzinfo=UTC)

# Гроссы, для которых `_salary_net_mid` (gross_to_net) даёт net-середины
# [175000, 220000, 260000, 300000, 350000, 390000] — посчитано напрямую в тесте ниже.
_GROSSES = (200_000, 250_000, 300_000, 350_000, 400_000, 450_000)


def _row(gross: int, *, scored_at: datetime = _NOW) -> tuple:
    salary = {"estimated_min": gross, "estimated_max": gross}
    return ("удалённо", salary, 80, {}, scored_at)


def test_target_zone_is_reported_even_when_market_sample_too_small():
    # Зона цели — из резюме, не из рыночной выборки; при n < min_samples остальные salary_*
    # гаснут честным None, а зона цели остаётся видна.
    result = compute_market_supply(
        [_row(400_000)], now=_NOW, target_min_net=374_000, target_max_net=450_000
    )
    assert result.available is False
    assert result.target_min_net == 374_000
    assert result.target_max_net == 450_000
    assert result.salary_points == []


def test_distribution_points_and_quartiles_match_direct_computation():
    rows = [_row(g) for g in _GROSSES]
    result = compute_market_supply(rows, now=_NOW, target_min_net=374_000, target_max_net=450_000)

    assert result.available is True
    assert result.salary_points == [175_000, 220_000, 260_000, 300_000, 350_000, 390_000]
    assert result.salary_median_net == 280_000
    assert result.salary_p25_net == 208_750
    assert result.salary_p75_net == 360_000
    assert result.target_min_net == 374_000
    assert result.target_max_net == 450_000


def test_points_omitted_when_salary_not_enough_even_if_measured_is():
    # 3 вакансии в окне (проходит min_samples по measured), но только 1 с читаемой вилкой —
    # гистограмма/четверти честно пустые, а не построены на одной точке.
    rows = [_row(400_000)]
    rows += [("офис", {}, 70, {}, _NOW) for _ in range(2)]
    result = compute_market_supply(rows, now=_NOW, min_samples=3)
    assert result.available is True
    assert result.salary_measured == 1
    assert result.salary_points == []
    assert result.salary_p25_net is None
    assert result.salary_p75_net is None


def test_second_job_track_does_not_enter_ruble_salary_points():
    # Э3.3: ставка второго трека не смешивается с рублёвой гистограммой.
    rows = [_row(400_000), _row(50), _row(350_000)]
    result = compute_market_supply(
        rows, now=_NOW, min_samples=3, tracks=["primary", "second_job", "primary"]
    )
    assert result.measured == 3
    assert result.salary_measured == 2
