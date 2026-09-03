"""Юнит-тесты compute_source_funnel: недонабор рисуется без %, available-гейт."""

from __future__ import annotations

from datetime import UTC, datetime

from core.domains.pipeline.source_funnel import MIN_SOURCE_SAMPLE, compute_source_funnel

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _jobs_hh(n: int, start: int = 1) -> list[tuple[int, str | None, str | None, str | None]]:
    return [(start + i, "applied", "hh", str(start + i)) for i in range(n)]


def _jobs_gm(n: int, start: int = 100) -> list[tuple[int, str | None, str | None, str | None]]:
    return [(start + i, "applied", "getmatch", f"gm_{start + i}") for i in range(n)]


def _jobs_habr(n: int, start: int = 200) -> list[tuple[int, str | None, str | None, str | None]]:
    return [(start + i, "applied", "habr", f"habr_{start + i}") for i in range(n)]


def _stages(jobs: list[tuple[int, str | None, str | None, str | None]]):
    return [(j[0], "Отклик", NOW) for j in jobs]


def test_available_false_when_all_groups_thin():
    jobs = _jobs_hh(3) + _jobs_gm(2)
    report = compute_source_funnel(jobs, _stages(jobs))
    assert report.available is False
    assert report.slices == []
    assert report.note is not None
    assert str(MIN_SOURCE_SAMPLE) in (report.note or "")


def test_thin_sibling_included_without_rates_when_one_group_enough():
    jobs = _jobs_hh(6) + _jobs_gm(2)
    report = compute_source_funnel(jobs, _stages(jobs))
    assert report.available is True
    by_src = {s.source: s for s in report.slices}
    assert set(by_src) == {"hh", "getmatch"}
    assert by_src["hh"].total == 6
    assert by_src["hh"].response_rate is not None
    assert by_src["getmatch"].total == 2
    assert by_src["getmatch"].response_rate is None
    assert by_src["getmatch"].offer_rate is None
    # Счётчики у тонкого среза всё равно есть.
    assert by_src["getmatch"].applied == 2


def test_empty_group_omitted():
    jobs = _jobs_hh(5)
    report = compute_source_funnel(jobs, _stages(jobs))
    assert report.available is True
    assert [s.source for s in report.slices] == ["hh"]


def test_habr_group_included_in_slices():
    """Хабр-группа попадает в срезы воронки по источнику (S11.1)."""
    jobs = _jobs_hh(6) + _jobs_habr(2)
    report = compute_source_funnel(jobs, _stages(jobs))
    assert report.available is True
    by_src = {s.source: s for s in report.slices}
    assert "habr" in by_src
    assert by_src["habr"].total == 2
    # Тонкий срез — rates не считаются (min_sample=5)
    assert by_src["habr"].response_rate is None
    assert by_src["habr"].offer_rate is None


def test_habr_group_with_enough_sample():
    """Хабр-группа с ≥5 вакансиями — rates считаются."""
    jobs = _jobs_hh(3) + _jobs_habr(5)
    report = compute_source_funnel(jobs, _stages(jobs))
    assert report.available is True
    by_src = {s.source: s for s in report.slices}
    assert "habr" in by_src
    assert by_src["habr"].total == 5
    assert by_src["habr"].response_rate is not None
    assert by_src["habr"].offer_rate is not None


def test_habr_label_present():
    """Лейбл Хабр-группы задан в SOURCE_GROUP_LABELS."""
    from core.domains.pipeline.source_funnel import SOURCE_GROUP_LABELS

    assert "habr" in SOURCE_GROUP_LABELS
    assert SOURCE_GROUP_LABELS["habr"] == "Хабр Карьера"


def test_habr_in_source_group_order():
    """SOURCE_GROUP_ORDER включает habr."""
    from core.domains.pipeline.source_funnel import SOURCE_GROUP_ORDER

    assert "habr" in SOURCE_GROUP_ORDER
