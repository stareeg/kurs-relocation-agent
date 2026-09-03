"""FR2-40: company_canonical при записи и план backfill без LLM."""

from __future__ import annotations

from core.domains.opportunities.companies.backfill import plan_updates
from core.domains.opportunities.jobs import company_canonical_for


def test_company_canonical_for_sber_and_empty():
    assert company_canonical_for("ПАО Сбербанк") == "Сбербанк"
    assert company_canonical_for("Sber") == "Сбербанк"
    assert company_canonical_for(None) is None
    assert company_canonical_for("") is None
    assert company_canonical_for("   ") is None


def test_plan_updates_fills_only_missing_by_default():
    rows = [
        (1, "ПАО Сбербанк", None),
        (2, "Yandex", "Яндекс"),  # уже заполнено — пропуск без force
        (3, "ООО Ромашка", ""),
        (4, None, None),  # нечего канонизировать
    ]
    planned = plan_updates(rows, force=False)
    assert planned == [
        (1, "Сбербанк", None),
        (3, "Ромашка", ""),
    ]


def test_plan_updates_force_rewrites_stale_canonical():
    rows = [
        (1, "ПАО Сбербанк", "ПАО Сбербанк"),  # устаревший «канон» = сырое имя
        (2, "Yandex", "Яндекс"),  # уже верный — пропуск
    ]
    planned = plan_updates(rows, force=True)
    assert planned == [(1, "Сбербанк", "ПАО Сбербанк")]
