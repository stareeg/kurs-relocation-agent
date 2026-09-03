"""Q&A по вакансии (`core.app.scenarios.vacancy_ask.ask`) должен уметь ответить, даже если
расширение не смогло прислать текст вакансии — напр. со страницы hh.ru «доп. вопрос при
отклике» (`/applicant/vacancy_response`), где в DOM нет разметки вакансии вообще, хотя сама
вакансия уже сохранена в Postgres при исходном скоринге.
"""

from __future__ import annotations

import pytest

from core.app.scenarios.vacancy_ask import ask
from core.domains.opportunities.jobs import Job
from core.kernel.errors import InvalidInput

VACANCY_TEXT = "Python backend разработчик. " * 5  # >= 50 символов


def _stored_job(**overrides) -> Job:
    defaults = dict(
        vacancy_id="123",
        vacancy_text=VACANCY_TEXT,
        title="Backend-разработчик",
        company="ООО Ромашка",
        salary_text="300 000 - 400 000",
    )
    defaults.update(overrides)
    return Job(**defaults)


@pytest.mark.asyncio
async def test_ask_falls_back_to_stored_job_when_dom_text_missing(monkeypatch):
    captured = {}

    async def fake_get_job(vacancy_id, *, account_id):
        assert vacancy_id == "123"
        assert account_id == 7
        return _stored_job()

    async def fake_ask_about_vacancy(record, question, history, *, bundle=None):
        captured["record"] = record
        return "ответ по вакансии"

    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr(
        "core.domains.preparation.asker.ask_about_vacancy", fake_ask_about_vacancy
    )

    result = await ask(
        "123",
        question="Какой стек?",
        vacancy_text=None,  # расширение потеряло DOM-контекст (страница опросника)
        account_id=7,
    )

    assert result.answer == "ответ по вакансии"
    assert captured["record"].vacancy_text == VACANCY_TEXT.strip()
    assert captured["record"].title == "Backend-разработчик"
    assert captured["record"].company == "ООО Ромашка"


@pytest.mark.asyncio
async def test_ask_keeps_request_metadata_over_stored_job(monkeypatch):
    captured = {}

    async def fake_get_job(vacancy_id, *, account_id):
        return _stored_job(title="Из БД", company="Из БД")

    async def fake_ask_about_vacancy(record, question, history, *, bundle=None):
        captured["record"] = record
        return "ok"

    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr(
        "core.domains.preparation.asker.ask_about_vacancy", fake_ask_about_vacancy
    )

    await ask(
        "123",
        question="Какой стек?",
        vacancy_text=None,
        title="Из запроса",
        account_id=7,
    )

    assert captured["record"].title == "Из запроса"
    assert captured["record"].company == "Из БД"


@pytest.mark.asyncio
async def test_ask_raises_when_no_text_anywhere(monkeypatch):
    async def fake_get_job(vacancy_id, *, account_id):
        return None

    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job
    )

    with pytest.raises(InvalidInput):
        await ask(
            "123",
            question="Какой стек?",
            vacancy_text=None,
            account_id=7,
        )


@pytest.mark.asyncio
async def test_ask_uses_request_text_without_db_lookup(monkeypatch):
    """Текст пришёл от расширения нормальный (со страницы самой вакансии) — к БД не лезем."""

    async def fake_get_job(vacancy_id, *, account_id):
        raise AssertionError("get_job_by_vacancy_id не должен вызываться")

    async def fake_ask_about_vacancy(record, question, history, *, bundle=None):
        return "ok"

    monkeypatch.setattr(
        "core.domains.opportunities.jobs.get_job_by_vacancy_id", fake_get_job
    )
    monkeypatch.setattr(
        "core.domains.preparation.asker.ask_about_vacancy", fake_ask_about_vacancy
    )

    result = await ask(
        "123",
        question="Какой стек?",
        vacancy_text=VACANCY_TEXT,
        account_id=7,
    )
    assert result.answer == "ok"
