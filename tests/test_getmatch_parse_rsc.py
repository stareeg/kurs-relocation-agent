"""Тесты RSC-парсера getmatch (Шаг 4 плана getmatch_refactoring_plan.md).

Проверяют трёхуровневую стратегию `parse_getmatch_vacancy_html`:
1. RSC Flight Stream `initialVacancy` (primary);
2. JSON-LD `JobPosting` (fallback);
3. regex DOM (запасной, анти-регрессия).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.domains.opportunities.sources.getmatch import (
    _extract_initial_vacancy,
    _extract_jsonld_jobposting,
    parse_getmatch_vacancy_html,
)
from core.kernel.errors import InvalidInput
from core.kernel.vacancy import RawVacancy

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "getmatch"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestExtractInitialVacancy:
    def test_full_vacancy(self):
        html = _read("vacancy_full.html")
        data = _extract_initial_vacancy(html)
        assert data is not None
        assert data["id"] == 35788
        assert data["position"] == "Data Scientist"
        assert data["company"]["name"] == "Selecty"
        assert data["salary_display_from"] == 220000
        assert data["salary_display_to"] == 310000
        assert data["specialization"] == "Data Scientist & Machine Learning"
        assert data["seniorities"] == ["senior"]

    def test_no_rsc_returns_none(self):
        assert _extract_initial_vacancy("<html><body>нет RSC</body></html>") is None


class TestExtractJsonLdJobPosting:
    def test_extracts_jobposting(self):
        html = _read("vacancy_full.html")
        data = _extract_jsonld_jobposting(html)
        assert data is not None
        assert data["@type"] == "JobPosting"
        assert data["title"] == "Data Scientist"
        assert data["hiringOrganization"]["name"] == "Selecty"

    def test_ignores_breadcrumblist(self):
        html = """<html><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":[]}
        </script></html>"""
        assert _extract_jsonld_jobposting(html) is None

    def test_no_jsonld_returns_none(self):
        assert _extract_jsonld_jobposting("<html><body>нет JSON-LD</body></html>") is None


class TestParseRscFullVacancy:
    def test_parse_rsc_full_vacancy(self):
        html = _read("vacancy_full.html")
        result = parse_getmatch_vacancy_html(
            html, url="https://getmatch.ru/vacancies/35788-data-scientist"
        )

        assert isinstance(result, RawVacancy)
        assert result.title == "Data Scientist"
        assert result.company == "Selecty"
        assert "220 000" in result.salary_text
        assert result.skills and "Python" in result.skills
        assert result.seniority == "senior"
        assert result.specialization == "Data Scientist & Machine Learning"
        assert result.vacancy_id == "gm_35788"
        assert result.url == "https://getmatch.ru/vacancies/35788-data-scientist"
        assert result.source == "getmatch"

        # text содержит структурированные инжекты + описание
        assert "Навыки: " in result.text
        assert "Профиль: Data Scientist & Machine Learning" in result.text
        assert "Что делать" in result.text

    def test_parse_rsc_hidden_company(self):
        html = _read("vacancy_hidden_company.html")
        result = parse_getmatch_vacancy_html(html)

        assert result.company == "Конфиденциально"
        assert result.skills is not None and len(result.skills) >= 8
        assert result.seniority == "senior"
        # зарплата без вилки: salary_description остаётся строкой
        assert "383 000" in result.salary_text


class TestFallbacks:
    def test_fallback_to_jsonld_when_no_rsc(self):
        # Вырезаем RSC-скрипты — JSON-LD должен выручить (title/company/зарплата).
        html = _read("vacancy_full.html")
        # Убираем только скрипты, которые и несут RSC Flight Stream (self.__next_f.push).
        import re

        no_rsc = re.sub(r"<script>self\.__next_f\.push.*?</script>", "", html, flags=re.DOTALL)
        assert _extract_initial_vacancy(no_rsc) is None

        result = parse_getmatch_vacancy_html(no_rsc)
        assert result.title == "Data Scientist"
        assert result.company == "Selecty"
        assert result.source == "getmatch"

    def test_fallback_to_regex_when_no_rsc_no_jsonld(self):
        # Без RSC и без JSON-LD — старый regex DOM (title из <h1>).
        html = (
            "<html><body>"
            '<section class="b-vacancy-header"><h1>Data Engineer</h1></section>'
            '<section class="b-vacancy-description"><p>Делаем DWH.</p></section>'
            '<a href="/companies/selecty">Selecty</a>'
            "</body></html>"
        )
        result = parse_getmatch_vacancy_html(html, url="https://getmatch.ru/vacancies/12345")

        assert result.title == "Data Engineer"
        assert result.company == "Selecty"
        assert result.vacancy_id == "gm_12345"
        assert "Делаем DWH" in result.text

    def test_empty_html_raises(self):
        with pytest.raises(InvalidInput, match="пустой HTML вакансии getmatch"):
            parse_getmatch_vacancy_html("   ")


class TestRegressionSelectorsPresent:
    def test_old_regex_selectors_still_present(self):
        """Анти-регрессия: старые regex не удалены — запасной слой на месте."""
        from core.domains.opportunities.sources.getmatch import (
            _AREA_TAG_RE,
            _COMPANY_RE,
            _DESC_RE,
            _FORMAT_TAG_RE,
            _SALARY_RE,
            _TITLE_RE,
        )

        assert _TITLE_RE is not None
        assert _COMPANY_RE is not None
        assert _SALARY_RE is not None
        assert _DESC_RE is not None
        assert _FORMAT_TAG_RE is not None
        assert _AREA_TAG_RE is not None
