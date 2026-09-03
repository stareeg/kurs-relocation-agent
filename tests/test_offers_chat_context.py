"""Чистая сборка хвоста чата «Офферы» — без БД."""

from __future__ import annotations

from datetime import UTC, datetime

from core.domains.offers.offers_chat_context import build_offers_chat_tail, format_offer_block
from core.domains.offers.store import Offer
from core.domains.profile import SearchProfile


def _offer(**kwargs: object) -> Offer:
    data: dict[str, object] = {
        "vacancy_id": "hh_1",
        "company": "Acme",
        "position": "Lead",
        **kwargs,
    }
    return Offer(**data)  # type: ignore[arg-type]


def test_format_offer_block_includes_tax_and_format() -> None:
    text = format_offer_block(
        _offer(
            base_salary=400_000,
            base_salary_tax_basis="net",
            work_format="remote",
            contract_type="ip",
            status="thinking",
        ),
        now=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert "на руки" in text
    assert "удалёнка" in text
    assert "ИП" in text
    assert "Acme" in text


def test_build_tail_empty_offers() -> None:
    profile = SearchProfile(
        title="Lead", is_filled=True, salary_min=300_000, target_grades=["Senior"]
    )
    text = build_offers_chat_tail([], profile)
    assert "Офферов пока нет" in text
    assert "Senior" in text


def test_build_tail_lists_offers_in_order() -> None:
    offers = [
        _offer(company="First", priority=1, base_salary=350_000),
        _offer(vacancy_id="hh_2", company="Second", priority=2, base_salary=420_000),
    ]
    text = build_offers_chat_tail(offers, None)
    assert text.index("First") < text.index("Second")
    assert "резюме ещё не заполнено" in text


def test_format_offer_block_lists_bonus_types_and_pct() -> None:
    text = format_offer_block(
        _offer(
            bonus_types=["annual", "kpi"],
            annual_bonus_pct=20,
            bonus="до 15% за OKR",
        ),
        now=datetime(2026, 8, 24, tzinfo=UTC),
    )
    assert "годовая 20% от года" in text
    assert "KPI" in text
    assert "до 15% за OKR" in text
