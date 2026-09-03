"""A-26: порт VacancySource — контракт, hh/getmatch, тест-двойник → скоринг."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RemoteFeasibility,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)
from core.domains.opportunities.service import score_from_source
from core.domains.opportunities.sources import (
    GetmatchVacancySource,
    HabrVacancySource,
    HhVacancySource,
    register_builtin_sources,
    to_vacancy_input,
)
from core.domains.opportunities.sources.getmatch import parse_getmatch_vacancy_html
from core.domains.opportunities.sources.hh import parse_hh_vacancy_html
from core.kernel import ports
from core.kernel.vacancy import RawVacancy
from tests.fakes import FakeLlm, FakeVacancySource

ROOT = Path(__file__).resolve().parents[1]
GM_FIXTURE = ROOT / "extension" / "tests" / "fixtures" / "getmatch-vacancy.html"


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def _score_stub() -> ScoreResult:
    return ScoreResult(
        overall_score=72,
        recommendation="apply",
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="500 000 ₽", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["ок"],
        cons=["нет вилки в тексте"],
        red_flags=[],
        one_line_verdict="ок",
    )


def test_builtin_sources_register_and_satisfy_protocol():
    register_builtin_sources()
    hh = ports.vacancy_source("hh")
    gm = ports.vacancy_source("getmatch")
    habr = ports.vacancy_source("habr")
    assert isinstance(hh, ports.VacancySource)
    assert isinstance(gm, ports.VacancySource)
    assert isinstance(habr, ports.VacancySource)
    assert isinstance(hh, HhVacancySource)
    assert isinstance(gm, GetmatchVacancySource)
    assert isinstance(habr, HabrVacancySource)


def test_new_source_is_one_file_plus_register():
    """Контракт плана: новый источник = файл + регистрация, без правок ядра."""

    class CustomSource:
        name = "custom"

        async def fetch(self, query: str) -> list[RawVacancy]:
            return [RawVacancy(vacancy_id=query, text="y" * 60, source="custom")]

        def parse(self, html: str) -> RawVacancy:
            return RawVacancy(text=html, source="custom")

    ports.register_vacancy_source(CustomSource())
    assert ports.vacancy_source("custom").name == "custom"


def test_hh_parse_vacancy_page_html():
    html = """
    <html><body>
    <h1 data-qa="vacancy-title">Lead LLM Engineer</h1>
    <a data-qa="vacancy-company-name" href="/employer/1">Acme AI</a>
    <div data-qa="vacancy-description"><p>Полная удалёнка. Вилка 500 000 на руки.
    Стек LangGraph, RAG, Python. Команда 5 человек.</p></div>
    <a href="https://hh.ru/vacancy/12345678">карточка</a>
    </body></html>
    """
    raw = parse_hh_vacancy_html(html)
    assert raw.vacancy_id == "12345678"
    assert raw.title == "Lead LLM Engineer"
    assert raw.company == "Acme AI"
    assert "LangGraph" in raw.text
    assert raw.source == "hh"
    assert isinstance(HhVacancySource().parse(html), RawVacancy)


def test_getmatch_parse_fixture_html():
    html = GM_FIXTURE.read_text(encoding="utf-8")
    raw = parse_getmatch_vacancy_html(
        html,
        url="https://getmatch.ru/vacancies/123456-senior-data-scientist",
    )
    assert raw.vacancy_id == "gm_123456"
    assert "Senior Data Scientist" in raw.title
    assert "MTS Web Services" in raw.company
    assert "Text-to-SQL" in raw.text or "Text2SQL" in raw.text or "SQL" in raw.text
    assert raw.source == "getmatch"
    assert GetmatchVacancySource().parse(html).title == raw.title


async def test_fake_source_passes_scoring_pipeline():
    """Приёмка A-26: тест-двойник источника проходит скоринг-пайплайн."""
    text = (
        "Lead LLM Engineer. Полная удалёнка по РФ. Зарплата 500 000 на руки. "
        "Стек: LangGraph, RAG, Python, FastAPI. Hands-on, без чистого менеджмента. "
        "Команда агентных систем в продукте."
    )
    raw = RawVacancy(
        vacancy_id="fake-1",
        url="https://example.test/v/1",
        title="Lead LLM Engineer",
        company="TestCo",
        text=text,
        salary_text="500 000 ₽",
        work_format="удалённо",
        source="fake",
    )
    fake_src = FakeVacancySource([raw])

    def _on_structured(feature: str, **kwargs):
        if feature == "remote_feasibility":
            return RemoteFeasibility(score=70, verdict="real")
        return _score_stub()

    fake_llm = FakeLlm(on_structured=_on_structured)

    with ports.use_ports(llm=fake_llm, vacancy_sources={"fake": fake_src}):
        outcomes = await score_from_source(
            "fake", "ignored-query", llm=fake_llm, persist=False, account_id=1
        )

    assert len(outcomes) == 1
    assert outcomes[0].score.recommendation in {"apply", "strong_apply"}
    assert outcomes[0].persisted is False
    assert "job_search" in fake_llm.features
    assert outcomes[0].remote is not None
    # Мост RawVacancy → VacancyInput сохраняет поля для персиста.
    vac = to_vacancy_input(raw)
    assert vac.vacancy_id == "fake-1"
    assert vac.company == "TestCo"
    assert len(vac.text) >= 50
