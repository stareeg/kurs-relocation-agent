"""Э2.1: извлечение условий работы + кэш по vacancy_id/text_hash + фильтр цитат."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.opportunities.models import TermEvidence, VacancyWorkTerms
from core.domains.opportunities.work_terms import (
    apply_quote_filter,
    get_or_extract_work_terms,
    load_work_terms,
    vacancy_text_hash,
)
from tests.fakes import FakeLlm, RaisingLlm

_JD = "Full-time employment, must be authorized to work, async-first culture, no time tracker."


class FakeDb:
    """Двойник Executor: одна строка на vacancy_id, как реальная таблица (PK)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.executes = 0

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return self.rows.get(args[0])

    async def execute(self, query: str, *args: Any) -> str:
        self.executes += 1
        vacancy_id, text_hash, terms = args
        self.rows[vacancy_id] = {"text_hash": text_hash, "terms": terms}
        return "INSERT 0 1"


def test_fake_quote_rolls_back_field(caplog: pytest.LogCaptureFixture) -> None:
    terms = VacancyWorkTerms(
        residency_required=True,
        evidence=[
            TermEvidence(field="residency_required", quote="this quote is not in the jd at all")
        ],
    )
    with caplog.at_level("WARNING"):
        filtered = apply_quote_filter(terms, _JD, vacancy_id="v-1")
    assert filtered.residency_required is False
    assert filtered.evidence == []
    assert any("поле откатывается" in r.message for r in caplog.records)


def test_real_quote_keeps_field() -> None:
    terms = VacancyWorkTerms(
        async_culture="async_first",
        evidence=[TermEvidence(field="async_culture", quote="async-first culture")],
    )
    filtered = apply_quote_filter(terms, _JD, vacancy_id="v-1")
    assert filtered.async_culture == "async_first"
    assert len(filtered.evidence) == 1


@pytest.mark.asyncio
async def test_get_or_extract_cache_hit_skips_llm() -> None:
    llm = FakeLlm(
        result=VacancyWorkTerms(
            engagement="employment",
            evidence=[TermEvidence(field="engagement", quote="Full-time employment")],
        )
    )
    db = FakeDb()
    first = await get_or_extract_work_terms("v-1", _JD, llm=llm, db=db)
    assert first.engagement == "employment"
    assert db.executes == 1
    cached = await get_or_extract_work_terms("v-1", _JD, llm=RaisingLlm(), db=db)
    assert cached.engagement == "employment"
    assert db.executes == 1


@pytest.mark.asyncio
async def test_get_or_extract_recomputes_when_text_changes() -> None:
    llm = FakeLlm(
        results=[
            VacancyWorkTerms(
                engagement="employment",
                evidence=[TermEvidence(field="engagement", quote="Full-time employment")],
            ),
            VacancyWorkTerms(
                engagement="contractor",
                evidence=[TermEvidence(field="engagement", quote="contractor invoice weekly")],
            ),
        ]
    )
    db = FakeDb()
    await get_or_extract_work_terms("v-1", _JD, llm=llm, db=db)
    other = "We hire contractor invoice weekly, part-time only, remote worldwide."
    assert vacancy_text_hash(other) != vacancy_text_hash(_JD)
    second = await get_or_extract_work_terms("v-1", other, llm=llm, db=db)
    assert second.engagement == "contractor"
    assert db.executes == 2
    loaded = await load_work_terms("v-1", db=db)
    assert loaded is not None
    assert loaded.engagement == "contractor"


def test_vacancy_input_without_hint_fields_still_validates() -> None:
    from core.domains.opportunities.models import VacancyInput

    vac = VacancyInput(text="A" * 60)
    assert vac.employment_type is None
    assert vac.location_raw is None
    assert vac.remote_type is None
