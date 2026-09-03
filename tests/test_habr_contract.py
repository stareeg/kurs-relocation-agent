"""Контракт HabrVacancySource: VacancySource, to_vacancy_input."""

from __future__ import annotations

import pytest

from core.domains.opportunities.sources import (
    HabrVacancySource,
    register_builtin_sources,
    to_vacancy_input,
)
from core.domains.opportunities.sources.habr import parse_habr_vacancy_html
from core.kernel import ports


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def test_habr_source_satisfies_vacancy_source_protocol():
    """HabrVacancySource — runtime_checkable VacancySource."""
    src = HabrVacancySource()
    assert src.name == "habr"
    assert isinstance(src, ports.VacancySource)


def test_habr_registers_as_builtin():
    """Регистрация через register_builtin_sources."""
    register_builtin_sources()
    habr = ports.vacancy_source("habr")
    assert isinstance(habr, HabrVacancySource)
    assert habr.name == "habr"


def test_habr_parse_via_protocol():
    """VacancySource.parse отдаёт RawVacancy."""
    html = """<html><script type="application/json" data-ssr-state="true">{"vacancy":{"id":10,"title":"Senior Dev","remoteWork":true,"employment":"full_time","qualification":"Senior","salary":{"from":300000,"to":500000,"currency":"rur","formatted":"300 000 – 500 000 ₽"},"skills":[{"title":"Python"}],"divisions":[{"title":"Разработка"}],"locations":[{"title":"Москва"}],"humanCityNames":"Москва","description":"<p>Работа</p>","company":{"title":"TestCo"}}}</script></html>"""
    raw = HabrVacancySource().parse(html)
    assert raw.vacancy_id == "habr_10"
    assert raw.source == "habr"
    assert "Квалификация: Senior" in raw.text
    assert "Навыки: Python" in raw.text


def test_to_vacancy_input_preserves_habr_fields():
    """Мост RawVacancy → VacancyInput: core-поля не теряются."""
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[1]
    HABR_FIXTURE = ROOT / "extension" / "tests" / "fixtures" / "habr-vacancy.html"
    html = HABR_FIXTURE.read_text(encoding="utf-8")
    raw = parse_habr_vacancy_html(html)

    vac = to_vacancy_input(raw)
    assert vac.vacancy_id == "habr_1000164602"
    assert vac.source == "habr"
    assert vac.title is not None and "Lead AI/ML" in vac.title
    assert vac.company == "Selecty"
    assert vac.salary_text == "от 400 000 ₽"
    assert vac.area == "Москва"
    assert vac.work_format == "удалённо"
    assert len(vac.text) >= 50