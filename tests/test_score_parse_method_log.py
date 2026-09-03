"""Шаг 6 getmatch_refactoring_plan.md + hh parser_health: уровень лог-события источника.

`parse_method=rsc` → INFO; `jsonld`/`dom` → WARNING.
hh `config`/`default`/`structural` → INFO; пустой `parse_method` — событие не пишется.
"""

from __future__ import annotations

import logging

from api.routers.opportunities.score import _log_parse_method
from api.schemas.jobs import ScoreRequest
from core.domains.opportunities.parser_health import MIN_SAMPLES, reset_hh_vacancy_parse_window

_LOGGER = "api.routers.opportunities.score"


def _make_req(method: str | None, source: str = "getmatch") -> ScoreRequest:
    return ScoreRequest(
        text="Оценка вакансии для скоринга." * 5, parse_method=method, source=source
    )


def test_rsc_is_info(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        _log_parse_method(_make_req("rsc"))
    assert any(
        "метод парсинга: rsc" in r.message and r.levelno == logging.INFO for r in caplog.records
    )


def test_jsonld_is_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _log_parse_method(_make_req("jsonld"))
    assert any(
        "метод парсинга: jsonld" in r.message and r.levelno == logging.WARNING
        for r in caplog.records
    )


def test_dom_is_warning(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        _log_parse_method(_make_req("dom"))
    assert any(
        "метод парсинга: dom" in r.message and r.levelno == logging.WARNING for r in caplog.records
    )


def test_empty_parse_method_emits_nothing(caplog) -> None:
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        _log_parse_method(_make_req(None, source="hh"))
    assert not any("метод парсинга" in r.message for r in caplog.records)


def test_hh_config_is_info(caplog) -> None:
    reset_hh_vacancy_parse_window()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        _log_parse_method(_make_req("config", source="vacancy_page"))
    rec = next(r for r in caplog.records if "метод парсинга: config" in r.message)
    assert rec.levelno == logging.INFO
    assert getattr(rec, "event", None) == "hh_parse_method"
    assert getattr(rec, "parse_method", None) == "config"
    assert not any(getattr(r, "event", None) == "hh_selectors_dead" for r in caplog.records)


def test_hh_structural_share_alerts_once(caplog) -> None:
    reset_hh_vacancy_parse_window()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        for _ in range(MIN_SAMPLES):
            _log_parse_method(_make_req("structural", source="vacancy_page"))
    dead = [r for r in caplog.records if getattr(r, "event", None) == "hh_selectors_dead"]
    assert len(dead) == 1
    assert dead[0].levelno == logging.WARNING
    assert "селекторы hh мертвы" in dead[0].message
    assert getattr(dead[0], "structural", None) == MIN_SAMPLES
    assert getattr(dead[0], "total", None) == MIN_SAMPLES
