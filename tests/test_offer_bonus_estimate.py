"""Редизайн «Офферы», шаг 8: детерминированная часть оценки помесячной премии (без LLM)."""

from __future__ import annotations

from core.domains.offers.bonus import (
    apply_bonus_patch,
    normalize_bonus_types,
    offer_bonus_types,
    snap_bonus_pct,
)
from core.domains.offers.models import OfferRecord
from core.domains.offers.offer_bonus_estimate import deterministic_bonus_monthly_equiv


def _offer(**kwargs) -> OfferRecord:
    base = {"vacancy_id": "v1", "company": "Acme", "position": "Lead LLM Engineer"}
    base.update(kwargs)
    return OfferRecord(**base)


def test_annual_with_amount_divides_by_12():
    offer = _offer(bonus_type="annual", bonus_amount=1_200_000)
    assert deterministic_bonus_monthly_equiv(offer) == 100_000


def test_quarterly_with_amount_divides_by_3():
    offer = _offer(bonus_type="quarterly", bonus_amount=300_000)
    assert deterministic_bonus_monthly_equiv(offer) == 100_000


def test_none_bonus_type_returns_none():
    offer = _offer(bonus_type="none")
    assert deterministic_bonus_monthly_equiv(offer) is None


def test_kpi_returns_none_deterministically():
    offer = _offer(bonus_type="kpi", bonus_amount=500_000)
    assert deterministic_bonus_monthly_equiv(offer) is None


def test_annual_without_amount_returns_none():
    offer = _offer(bonus_type="annual", bonus_amount=None)
    assert deterministic_bonus_monthly_equiv(offer) is None


def test_annual_pct_of_monthly_salary():
    offer = _offer(
        bonus_types=["annual"],
        base_salary=500_000,
        base_salary_period="month",
        annual_bonus_pct=20,
    )
    assert deterministic_bonus_monthly_equiv(offer) == 100_000


def test_annual_pct_adds_to_yearly_package_never_replaces_it():
    """10% годовых — добавка к окладу, годовой пакет растёт, а не сжимается до премии."""
    monthly = 500_000
    offer = _offer(
        bonus_types=["annual"],
        base_salary=monthly,
        base_salary_period="month",
        annual_bonus_pct=10,
    )
    extra = deterministic_bonus_monthly_equiv(offer)
    assert extra == 50_000
    annual_without = monthly * 12
    annual_with = annual_without + extra * 12
    assert annual_with == 6_600_000
    assert annual_with > annual_without


def test_quarterly_pct_of_monthly_salary():
    offer = _offer(
        bonus_types=["quarterly"],
        base_salary=500_000,
        base_salary_period="month",
        quarterly_bonus_pct=20,
    )
    assert deterministic_bonus_monthly_equiv(offer) == 100_000


def test_annual_and_quarterly_pcts_add_up():
    offer = _offer(
        bonus_types=["annual", "quarterly"],
        base_salary=500_000,
        annual_bonus_pct=20,
        quarterly_bonus_pct=10,
    )
    assert deterministic_bonus_monthly_equiv(offer) == 150_000


def test_annual_pct_with_yearly_salary():
    offer = _offer(
        bonus_types=["annual"],
        base_salary=6_000_000,
        base_salary_period="year",
        annual_bonus_pct=20,
    )
    assert deterministic_bonus_monthly_equiv(offer) == 100_000


def test_kpi_plus_annual_still_needs_llm():
    offer = _offer(
        bonus_types=["annual", "kpi"],
        base_salary=500_000,
        annual_bonus_pct=20,
    )
    assert deterministic_bonus_monthly_equiv(offer) is None


def test_welcome_only_has_no_monthly_equiv():
    offer = _offer(bonus_types=["welcome"], signon=300_000, base_salary=500_000)
    assert deterministic_bonus_monthly_equiv(offer) is None


def test_normalize_bonus_types_canonical_and_dedupes():
    assert normalize_bonus_types(["kpi", "annual", "annual", "none"]) == ["annual", "kpi"]
    assert normalize_bonus_types("quarterly") == ["quarterly"]
    assert normalize_bonus_types("none") == []
    assert normalize_bonus_types(None) == []


def test_offer_bonus_types_falls_back_to_singular():
    assert offer_bonus_types([], "annual") == ["annual"]
    assert offer_bonus_types(["kpi"], "annual") == ["kpi"]


def test_snap_bonus_pct():
    assert snap_bonus_pct(18) == 20
    assert snap_bonus_pct(5) == 5
    assert snap_bonus_pct(0) is None
    assert snap_bonus_pct(None) is None


def test_apply_bonus_patch_types_win_over_singular():
    out = apply_bonus_patch({"bonus_types": ["welcome", "annual"], "bonus_type": "kpi"})
    assert out["bonus_types"] == ["annual", "welcome"]
    assert out["bonus_type"] == "annual"
