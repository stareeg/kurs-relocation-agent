"""Шаг 6: доля method=structural среди разборов вакансий hh за час."""

from __future__ import annotations

from core.domains.opportunities.parser_health import (
    ALERT_COOLDOWN_S,
    MIN_SAMPLES,
    WINDOW_S,
    HhVacancyParseWindow,
    note_hh_vacancy_parse,
    reset_hh_vacancy_parse_window,
)


def test_ignores_non_hh_methods() -> None:
    window = HhVacancyParseWindow()
    assert window.observe("rsc", now=0.0) is None
    assert window.observe("serp_json", now=1.0) is None
    assert window.observe("jsonld", now=2.0) is None


def test_below_min_samples_no_alert() -> None:
    window = HhVacancyParseWindow()
    now = 0.0
    for i in range(MIN_SAMPLES - 1):
        assert window.observe("structural", now=now + i) is None


def test_all_structural_alerts() -> None:
    window = HhVacancyParseWindow()
    alert = None
    for i in range(MIN_SAMPLES):
        alert = window.observe("structural", now=float(i))
    assert alert is not None
    assert alert.total == MIN_SAMPLES
    assert alert.structural == MIN_SAMPLES
    assert alert.share == 1.0


def test_ten_percent_exactly_does_not_alert() -> None:
    window = HhVacancyParseWindow()
    now = 0.0
    for i in range(36):
        assert window.observe("config", now=now + i) is None
    for i in range(4):
        assert window.observe("structural", now=now + 36 + i) is None


def test_above_ten_percent_alerts() -> None:
    window = HhVacancyParseWindow()
    now = 0.0
    for i in range(9):
        assert window.observe("config", now=now + i) is None
    # 1/10 == 10% — порог строго больше, не алертим.
    assert window.observe("structural", now=now + 9) is None
    alert = window.observe("structural", now=now + 10)
    assert alert is not None
    assert alert.total == 11
    assert alert.structural == 2


def test_old_samples_leave_the_window() -> None:
    window = HhVacancyParseWindow()
    for i in range(MIN_SAMPLES):
        window.observe("structural", now=float(i))
    later = WINDOW_S + MIN_SAMPLES + 1
    for i in range(MIN_SAMPLES):
        assert window.observe("config", now=later + i) is None


def test_alert_cooldown() -> None:
    window = HhVacancyParseWindow()
    alert = None
    for i in range(MIN_SAMPLES):
        alert = window.observe("structural", now=float(i))
    assert alert is not None
    assert window.observe("structural", now=float(MIN_SAMPLES)) is None
    # Через час старые точки ещё не все выпали: добираем structural перед границей
    # cooldown, иначе окно опустеет и алерт молчит из-за MIN_SAMPLES, а не паузы.
    edge = (MIN_SAMPLES - 1) + ALERT_COOLDOWN_S
    for i in range(1, MIN_SAMPLES):
        assert window.observe("structural", now=edge - MIN_SAMPLES + i) is None
    second = window.observe("structural", now=edge)
    assert second is not None


def test_module_singleton_reset() -> None:
    reset_hh_vacancy_parse_window()
    for i in range(MIN_SAMPLES):
        note_hh_vacancy_parse("structural", now=float(i))
    reset_hh_vacancy_parse_window()
    assert note_hh_vacancy_parse("structural", now=100.0) is None
