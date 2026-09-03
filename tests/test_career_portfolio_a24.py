"""A-24: черновик портфолио из ResumeData (и хелперы debrief/offer)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.domains.career.models import PortfolioItem
from core.domains.career.portfolio import (
    draft_portfolio_from_debrief,
    draft_portfolio_from_offer,
    draft_portfolio_from_resume,
    record_portfolio_from_debrief,
    record_portfolio_from_offer,
)
from core.domains.offers.store import Offer
from core.domains.preparation.debrief import DebriefRecord
from core.domains.profile.model import Experience, ResumeData
from core.kernel.events import InterviewDebriefed, OfferReceived
from core.kernel.ids import OfferId, VacancyId

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> ResumeData:
    raw = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))
    return ResumeData.model_validate(raw)


def test_draft_portfolio_from_resume_smoke_frontend() -> None:
    """Критерий A-24: из ResumeData собирается черновой список элементов."""
    data = _load_fixture("resume_smoke_frontend.json")
    items = draft_portfolio_from_resume(data)

    assert len(items) == 2
    assert items[0].project.startswith("ООО «ВебПродукт»")
    assert items[0].role == "Senior Frontend Developer"
    assert "30%" in items[0].outcome  # результат в цифрах из description
    assert items[0].artifact_url == "https://example.com"
    assert items[0].source_ref.startswith("resume:exp:0:")

    assert items[1].role == "Frontend Developer"
    # В description есть «Vue 2» — строка с цифрой уходит в outcome.
    assert "Vue" in items[1].outcome
    assert items[1].source_ref.startswith("resume:exp:1:")


def test_draft_skips_empty_experience() -> None:
    data = ResumeData(
        experience=[
            Experience(company="", position="", description="ничего"),
            Experience(company="Acme", position="Dev", description="p95 < 200ms"),
        ]
    )
    items = draft_portfolio_from_resume(data)
    assert len(items) == 1
    assert items[0].project == "Acme"
    assert "200" in items[0].outcome


def test_draft_empty_resume() -> None:
    assert draft_portfolio_from_resume(ResumeData()) == []


def test_draft_from_debrief_strong_answers() -> None:
    items = draft_portfolio_from_debrief(
        vacancy_id="v1",
        company="Acme",
        strong_answers=["Рассказал про RAG", "Показал метрики latency"],
        summary="Сильный тех-раунд",
        debrief_id=12,
    )
    assert len(items) == 1
    assert items[0].project == "Acme"
    assert "RAG" in items[0].outcome
    assert items[0].source_ref == "debrief:12"
    assert items[0].notes == "Сильный тех-раунд"


def test_draft_from_offer_negotiation() -> None:
    items = draft_portfolio_from_offer(
        vacancy_id="gm_9",
        company="BigTech",
        position="Lead",
        base_salary=500_000,
        negotiation_points=["Поднять base на 10%", "Sign-on 300k"],
    )
    assert len(items) == 1
    assert items[0].project == "Оффер · BigTech"
    assert items[0].role == "Lead"
    assert "500 000" in items[0].outcome
    assert "Sign-on" in items[0].outcome
    assert items[0].source_ref == "offer:gm_9"


async def test_record_portfolio_from_debrief_with_strong_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Этап 5.2 (plans/career_redesign_2026_08_26.md): разбор с сильными ответами →
    достижение сразу, без промежуточного статуса «черновик» (решение владельца п.3)."""
    record = DebriefRecord(
        id=9,
        vacancy_id="gm_1",
        stage="theory",
        summary="Сильный раунд",
        analysis={"strong_answers": ["Рассказал про RAG"]},
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        "core.domains.preparation.debrief.get_debrief", AsyncMock(return_value=record)
    )
    saved: list[PortfolioItem] = []

    async def _insert(item: PortfolioItem, *, account_id=None, db=None) -> PortfolioItem:
        saved.append(item)
        return item.model_copy(update={"id": len(saved)})

    monkeypatch.setattr("core.domains.career.portfolio.insert_portfolio_item", _insert)

    out = await record_portfolio_from_debrief(
        InterviewDebriefed(
            vacancy_id=VacancyId("gm_1"), stage="theory", debrief_id=9, account_id=1
        ),
        account_id=1,
    )
    assert len(out) == 1
    assert saved
    assert "RAG" in saved[0].outcome
    assert saved[0].source_ref == "debrief:9"


async def test_record_portfolio_from_debrief_without_strong_answers_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = DebriefRecord(
        id=10,
        vacancy_id="gm_2",
        stage="theory",
        analysis={"strong_answers": []},
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        "core.domains.preparation.debrief.get_debrief", AsyncMock(return_value=record)
    )
    insert = AsyncMock()
    monkeypatch.setattr("core.domains.career.portfolio.insert_portfolio_item", insert)

    out = await record_portfolio_from_debrief(
        InterviewDebriefed(
            vacancy_id=VacancyId("gm_2"), stage="theory", debrief_id=10, account_id=1
        ),
        account_id=1,
    )
    assert out == []
    insert.assert_not_called()


async def test_record_portfolio_from_offer_uses_negotiation_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offer = Offer(
        vacancy_id=VacancyId("hh_1"),
        company="BigTech",
        position="Lead",
        base_salary=500_000,
        negotiation={"arguments": [{"fact": "p95", "wording": "Поднять base на 10%"}]},
    )
    monkeypatch.setattr("core.domains.offers.store.load_offer", AsyncMock(return_value=offer))
    saved: list[PortfolioItem] = []

    async def _insert(item: PortfolioItem, *, account_id=None, db=None) -> PortfolioItem:
        saved.append(item)
        return item.model_copy(update={"id": len(saved)})

    monkeypatch.setattr("core.domains.career.portfolio.insert_portfolio_item", _insert)

    out = await record_portfolio_from_offer(
        OfferReceived(
            offer_id=OfferId("hh_1"),
            vacancy_id=VacancyId("hh_1"),
            company="BigTech",
            account_id=1,
        ),
        account_id=1,
    )
    assert len(out) == 1
    assert "Поднять base" in saved[0].outcome
    assert saved[0].source_ref == "offer:hh_1"


async def test_record_portfolio_from_offer_missing_offer_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.domains.offers.store.load_offer", AsyncMock(return_value=None))

    out = await record_portfolio_from_offer(
        OfferReceived(offer_id=OfferId("x"), vacancy_id=VacancyId("x"), company="", account_id=1),
        account_id=1,
    )
    assert out == []
