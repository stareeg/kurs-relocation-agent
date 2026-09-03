"""Тесты источника career.habr.com: SSR-JSON, JSON-LD fallback, маппинг грейда."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.domains.opportunities.sources.habr import (
    _canonical_vacancy_id,
    extract_habr_numeric_id_from_text,
    map_habr_qualification,
    parse_habr_vacancy_html,
)
from core.kernel.errors import InvalidInput
from core.kernel.vacancy import RawVacancy

ROOT = Path(__file__).resolve().parents[1]
HABR_FIXTURE = ROOT / "extension" / "tests" / "fixtures" / "habr-vacancy.html"


class TestExtractHabrNumericIdFromText:
    def test_polnyj_url_habr(self):
        assert extract_habr_numeric_id_from_text(
            "https://career.habr.com/vacancies/1000164602"
        ) == "1000164602"

    def test_url_s_tekstom_vokrug(self):
        assert extract_habr_numeric_id_from_text(
            "открыл вакансию https://career.habr.com/vacancies/1000164602 вчера"
        ) == "1000164602"

    def test_invalid_host_returns_none(self):
        assert extract_habr_numeric_id_from_text(
            "https://habr.com/ru/vacancies/1000164602"
        ) is None

    def test_empty_text_returns_none(self):
        assert extract_habr_numeric_id_from_text("") is None
        assert extract_habr_numeric_id_from_text(None) is None


class TestCanonicalVacancyId:
    def test_prefix_habr(self):
        assert _canonical_vacancy_id("1000164602") == "habr_1000164602"


class TestMapHabrQualification:
    def test_match(self):
        # target = Senior → вакансия Senior = match
        assert map_habr_qualification("Senior", "Senior") == "match"

    def test_above(self):
        # target = Middle → вакансия Senior = above
        assert map_habr_qualification("Senior", "Middle") == "above"
        # target = Junior → вакансия Lead = above
        assert map_habr_qualification("Lead", "Junior") == "above"

    def test_slightly_below(self):
        # target = Senior → вакансия Middle = slightly_below (на одну ступень ниже)
        assert map_habr_qualification("Middle", "Senior") == "slightly_below"

    def test_far_below(self):
        # target = Lead → вакансия Junior = far_below (на 2+ ступени ниже)
        assert map_habr_qualification("Junior", "Lead") == "far_below"
        assert map_habr_qualification("Intern", "Senior") == "far_below"

    def test_unknown_target_defaults_to_senior(self):
        # target не в _HABR_LADDER → индекс 3 (Senior)
        assert map_habr_qualification("Senior", "Lead") == "slightly_below"  # 3 vs 4
        assert map_habr_qualification("Senior", "UnknownRole") == "match"  # 3 vs 3

    def test_unknown_qualification_off_profile(self):
        # qualification не в _HABR_LADDER → off_profile
        assert map_habr_qualification("Director", "Senior") == "off_profile"
        assert map_habr_qualification("C-level", "Lead") == "off_profile"

    def test_intern_junior_above(self):
        # target = Junior → вакансия Middle = above
        assert map_habr_qualification("Middle", "Junior") == "above"


class TestParseHabrVacancyHtml:
    def test_ssr_json_primary(self):
        html = HABR_FIXTURE.read_text(encoding="utf-8")
        raw = parse_habr_vacancy_html(html, url="https://career.habr.com/vacancies/1000164602")

        assert isinstance(raw, RawVacancy)
        assert raw.source == "habr"
        assert raw.vacancy_id == "habr_1000164602"
        assert raw.url == "https://career.habr.com/vacancies/1000164602"
        assert "Lead AI/ML Engineer" in raw.title
        assert raw.company == "Selecty"
        assert raw.salary_text == "от 400 000 ₽"
        assert raw.area == "Москва"
        assert raw.work_format == "удалённо"

        # Инжект структурированных данных в text
        assert "Навыки: Python, PyTorch, Transformers, LangGraph, GPT, RAG, FastAPI" in raw.text
        assert "Квалификация: Lead" in raw.text
        assert "Специализации: Машинное обучение" in raw.text
        assert "мультиагентных LLM-систем" in raw.text  # описание (lowercase после strip_html)
        assert "RAG-пайплайнов" in raw.text

    def test_ssr_json_office_format(self):
        html = """<html><script type="application/json" data-ssr-state="true">{"vacancy":{"id":1,"title":"Dev","remoteWork":false,"employment":"full_time","qualification":"Middle","salary":{"from":200000,"to":300000,"currency":"rur","formatted":"200 000 – 300 000 ₽"},"skills":[{"title":"Java"},{"title":"Spring"}],"divisions":[{"title":"Бэкенд"}],"locations":[{"title":"Санкт-Петербург"}],"humanCityNames":"Санкт-Петербург","description":"<p>Офисная работа</p>","company":{"title":"TestCo"}}}</script></html>"""
        raw = parse_habr_vacancy_html(html)

        assert raw.vacancy_id == "habr_1"
        assert raw.title == "Dev"
        assert raw.company == "TestCo"
        assert raw.salary_text == "200 000 – 300 000 ₽"
        assert raw.area == "Санкт-Петербург"
        assert raw.work_format == ""  # remoteWork=false → офис (но пустая строка, т.к. фолбэк)

    def test_ssr_json_no_area_falls_back_to_locations(self):
        # humanCityNames пуст, используем первый locations[0].title
        html = """<html><script type="application/json" data-ssr-state="true">{"vacancy":{"id":2,"title":"Eng","remoteWork":true,"skills":[],"divisions":[],"locations":[{"title":"Казань"}],"humanCityNames":"","description":"","company":{"title":"TestCo"}}}</script></html>"""
        raw = parse_habr_vacancy_html(html)

        assert raw.area == "Казань"

    def test_json_ld_fallback(self):
        html = """<html><script type="application/ld+json">{"@context":"https://schema.org/","@type":"JobPosting","title":"Senior Python Developer","hiringOrganization":{"@type":"Organization","name":"Acme Corp"},"baseSalary":{"@type":"MonetaryAmount","currency":"RUB","value":{"@type":"QuantitativeValue","unitText":"MONTH","minValue":500000}},"description":"Разработка высоконагруженных сервисов на Python. Удалёнка.","identifier":"1000164603"}</script></html>"""
        raw = parse_habr_vacancy_html(html)

        assert isinstance(raw, RawVacancy)
        assert raw.source == "habr"
        assert raw.vacancy_id == "habr_1000164603"
        assert raw.title == "Senior Python Developer"
        assert raw.company == "Acme Corp"
        assert raw.salary_text == "от 500000 ₽"
        assert "высоконагруженных сервисов" in raw.text

    def test_json_ld_missing_identifier(self):
        html = """<html><script type="application/ld+json">{"@type":"JobPosting","title":"Dev","description":"Работа","hiringOrganization":{"name":"Co"}}</script></html>"""
        raw = parse_habr_vacancy_html(html)

        # Нет identifier → vacancy_id пуст
        assert raw.vacancy_id == ""
        assert raw.title == "Dev"
        assert raw.company == "Co"

    def test_empty_html_raises(self):
        with pytest.raises(InvalidInput, match="пустой HTML вакансии Хабр"):
            parse_habr_vacancy_html("")

    def test_no_ssr_and_no_json_ld_raises(self):
        html = "<html><body>обычная страница</body></html>"
        with pytest.raises(InvalidInput, match="не удалось разобрать"):
            parse_habr_vacancy_html(html)

    def test_malformed_ssr_json_graceful_fallback(self):
        # Битый JSON в SSR → fallback на JSON-LD
        html = """<html>
        <script type="application/json" data-ssr-state="true">{broken</script>
        <script type="application/ld+json">{"@type":"JobPosting","title":"Dev","description":"Работа. Python.","hiringOrganization":{"name":"Co"},"identifier":"42"}</script>
        </html>"""
        raw = parse_habr_vacancy_html(html)

        assert raw.vacancy_id == "habr_42"
        assert raw.title == "Dev"
        assert raw.source == "habr"