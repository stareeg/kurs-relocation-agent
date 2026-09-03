"""D-07: внешние показания рынка — чистые функции `normalize_query`/`zone_for_index`."""

from __future__ import annotations

from core.domains.market.external_signals import normalize_query, zone_for_index


def test_normalize_query_lowercases_and_collapses_whitespace():
    assert normalize_query("  Python   Developer  ") == "python developer"


def test_normalize_query_is_idempotent_for_dedup():
    a = normalize_query("Backend  Engineer")
    b = normalize_query("backend engineer")
    assert a == b


def test_zone_for_index_boundaries_match_plan_2_6_3():
    assert zone_for_index(0) == "рынок соискателя"
    assert zone_for_index(4) == "рынок соискателя"
    assert zone_for_index(4.1) == "равновесие"
    assert zone_for_index(7) == "равновесие"
    assert zone_for_index(7.1) == "высокая конкуренция"
    assert zone_for_index(11.9) == "высокая конкуренция"
    assert zone_for_index(12) == "крайне высокая конкуренция"
    assert zone_for_index(20) == "крайне высокая конкуренция"
