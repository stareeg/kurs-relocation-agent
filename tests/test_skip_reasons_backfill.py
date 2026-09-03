"""Этап 7 §7.1: план бэкфилла canonical_reason без LLM (D17)."""

from __future__ import annotations

from core.domains.opportunities.skip_reasons_backfill import plan_updates


def test_plan_updates_fills_only_missing_by_default():
    rows = [
        (1, "Сомнительная компания", None),  # legacy-строка → канон
        (2, "Низкая зарплата", "Низкая зарплата"),  # уже верно — пропуск без force
        (3, "Пропущено вручную", ""),
        (4, "Диалог закрыт", None),
    ]
    planned = plan_updates(rows, force=False)
    assert planned == [
        (1, "Избегать компанию", None),
        (3, "Избегать компанию", ""),
        (4, "Избегать компанию", None),
    ]


def test_plan_updates_force_rewrites_stale_canonical():
    rows = [
        (1, "Риск выгорания", "Риск выгорания"),  # устаревший «канон» = старое название
        (2, "Низкая зарплата", "Низкая зарплата"),  # уже верно — пропуск
    ]
    planned = plan_updates(rows, force=True)
    assert planned == [(1, "Не та роль (IC vs рук)", "Риск выгорания")]


def test_plan_updates_never_needs_llm_because_canon_is_total():
    """canonical_skip_reason не возвращает пусто ни для одной строки — бэкфилл детерминирован."""
    rows = [(1, "какая-то совсем случайная причина без ключевых слов", None)]
    planned = plan_updates(rows, force=False)
    assert planned == [(1, "Избегать компанию", None)]
