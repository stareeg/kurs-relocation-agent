"""Э3.3: валютная шкала второго трека — без FX, порог 8 наблюдений."""

from __future__ import annotations

from core.domains.market.salary_benchmark import FX_RATE_MIN_N, compute_fx_rate_scale


def _terms(currency: str, period: str, lo: int, hi: int | None = None) -> dict:
    return {
        "currency": currency,
        "rate_period": period,
        "rate_min": lo,
        "rate_max": hi if hi is not None else lo,
    }


def test_rub_and_empty_currency_are_excluded():
    scale = compute_fx_rate_scale(
        [_terms("RUB", "month", 300_000), _terms("", "hour", 50), _terms("USD", "hour", 45)]
    )
    assert scale.available is True
    assert [b.currency for b in scale.buckets] == ["USD"]
    assert scale.buckets[0].n == 1
    assert scale.buckets[0].enough_data is False
    assert scale.buckets[0].median_mid is None


def test_below_min_n_no_invented_median():
    rows = [_terms("USD", "hour", 40 + i) for i in range(3)]
    scale = compute_fx_rate_scale(rows)
    assert scale.min_n == FX_RATE_MIN_N
    assert scale.buckets[0].n == 3
    assert scale.buckets[0].enough_data is False
    assert scale.buckets[0].median_mid is None


def test_eight_observations_give_median():
    rows = [_terms("USD", "hour", 40 + i) for i in range(9)]
    scale = compute_fx_rate_scale(rows)
    assert scale.buckets[0].enough_data is True
    assert scale.buckets[0].n == 9
    assert scale.buckets[0].median_mid == 44


def test_currencies_are_not_mixed():
    rows = [_terms("USD", "hour", 50) for _ in range(8)]
    rows += [_terms("EUR", "hour", 40) for _ in range(8)]
    scale = compute_fx_rate_scale(rows)
    by_cur = {b.currency: b.median_mid for b in scale.buckets}
    assert by_cur["USD"] != by_cur["EUR"]
    assert set(by_cur) == {"EUR", "USD"}


def test_unknown_period_dropped():
    scale = compute_fx_rate_scale([_terms("USD", "unknown", 45) for _ in range(10)])
    assert scale.available is False
    assert scale.buckets == []
