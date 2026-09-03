"""D-06: свои офферы на оси денег — `compute_live_offer_points`, чистая функция."""

from __future__ import annotations

from core.domains.market.salary_benchmark import compute_live_offer_points
from core.domains.offers.store import Offer


def _offer(**kwargs) -> Offer:
    base = {"vacancy_id": "v1", "company": "Сбер"}
    base.update(kwargs)
    return Offer(**base)


def test_month_net_offer_matches_raw_card_value():
    # Уже в месяц/net — карточка «Офферов» показывает тот же raw base_salary в поле «Оклад»,
    # нормализация не должна его менять (готово-критерий плана D-06).
    offer = _offer(
        company="Сбер",
        base_salary=540_000,
        base_salary_period="month",
        base_salary_tax_basis="net",
    )
    points = compute_live_offer_points([offer])
    assert len(points) == 1
    assert points[0].company == "Сбер"
    assert points[0].monthly_net == 540_000


def test_two_offers_give_both_points_from_the_plan_example():
    offers = [
        _offer(company="Сбер", base_salary=540_000, base_salary_period="month",
               base_salary_tax_basis="net"),
        _offer(vacancy_id="v2", company="ПОСК", base_salary=450_000, base_salary_period="month",
               base_salary_tax_basis="net"),
    ]
    points = compute_live_offer_points(offers)
    by_company = {p.company: p.monthly_net for p in points}
    assert by_company == {"Сбер": 540_000, "ПОСК": 450_000}


def test_annual_gross_offer_is_converted_to_monthly_net():
    offer = _offer(base_salary=6_000_000, base_salary_period="year", base_salary_tax_basis="gross")
    points = compute_live_offer_points([offer])
    # 6_000_000 / 12 = 500_000 gross/мес → net ×0.87 = 435_000, округлено до шага рынка (10к).
    assert points[0].monthly_net == 440_000


def test_offer_without_base_salary_is_skipped():
    offer = _offer(base_salary=None)
    assert compute_live_offer_points([offer]) == []


def test_non_rub_offer_is_skipped_no_fx_conversion():
    offer = _offer(base_salary=5_000, base_salary_currency="USD", base_salary_tax_basis="net")
    assert compute_live_offer_points([offer]) == []


def test_zero_base_salary_is_skipped():
    offer = _offer(base_salary=0)
    assert compute_live_offer_points([offer]) == []
