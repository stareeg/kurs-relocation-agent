"""`update_fact` / `delete_fact` / комбинированные фильтры `list_active_facts` (Э9.4).

Требует живой Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from core.domains.career.facts import load_facts_context_block
from core.domains.career.models import CareerFact
from core.domains.career.repo import (
    delete_fact,
    insert_fact,
    list_active_facts,
    merge_fact,
    update_fact,
)
from tests.rls_isolation import two_accounts

pytestmark = pytest.mark.db


async def test_pin_clears_expiry(two_accounts) -> None:
    account_a, _account_b = two_accounts
    fact = await insert_fact(
        CareerFact(
            fact="Хочет удалёнку",
            fact_type="preference",
            source_kind="debrief",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
        account_id=account_a,
    )
    assert fact.expires_at is not None

    pinned = await update_fact(fact.id, account_id=account_a, pinned=True)
    assert pinned is not None
    assert pinned.expires_at is None


async def test_edit_text_does_not_touch_expiry(two_accounts) -> None:
    account_a, _account_b = two_accounts
    expires = datetime.now(UTC) + timedelta(days=30)
    fact = await insert_fact(
        CareerFact(fact="Старый текст", fact_type="note", source_kind="manual", expires_at=expires),
        account_id=account_a,
    )

    edited = await update_fact(fact.id, account_id=account_a, fact="Новый текст")
    assert edited is not None
    assert edited.fact == "Новый текст"
    assert edited.expires_at is not None  # не тронут


async def test_update_fact_wrong_account_returns_none(two_accounts) -> None:
    account_a, account_b = two_accounts
    fact = await insert_fact(
        CareerFact(fact="Чужой факт", fact_type="note", source_kind="manual"),
        account_id=account_a,
    )
    result = await update_fact(fact.id, account_id=account_b, fact="Подмена")
    assert result is None


async def test_delete_fact_removes_row_and_reports_true(two_accounts) -> None:
    account_a, _account_b = two_accounts
    fact = await insert_fact(
        CareerFact(fact="Удалить меня", fact_type="note", source_kind="manual"),
        account_id=account_a,
    )
    assert await delete_fact(fact.id, account_id=account_a) is True
    assert await delete_fact(fact.id, account_id=account_a) is False  # уже удалён


async def test_delete_fact_wrong_account_returns_false(two_accounts) -> None:
    account_a, account_b = two_accounts
    fact = await insert_fact(
        CareerFact(fact="Чужой факт", fact_type="note", source_kind="manual"),
        account_id=account_a,
    )
    assert await delete_fact(fact.id, account_id=account_b) is False
    # факт всё ещё виден владельцу — чужое удаление не прошло
    remaining = await list_active_facts(account_id=account_a)
    assert any(f.id == fact.id for f in remaining)


async def test_deleted_fact_vanishes_from_prompt_context(two_accounts) -> None:
    """Сквозной эффект (не только 200 от роутера): удалённый факт пропадает из промпта."""
    account_a, _account_b = two_accounts
    fact = await insert_fact(
        CareerFact(fact="Уникальный маркер XYZ123", fact_type="note", source_kind="manual"),
        account_id=account_a,
    )
    before = await load_facts_context_block(account_id=account_a)
    assert "XYZ123" in before

    await delete_fact(fact.id, account_id=account_a)

    after = await load_facts_context_block(account_id=account_a)
    assert "XYZ123" not in after


async def test_merge_fact_updates_text_confidence_source_and_payload(two_accounts) -> None:
    """Этап 4.1 (plans/career_redesign_2026_08_26.md): мердж между разборами обновляет
    строку вместо новой — новая формулировка, уверенность, источник и payload."""
    account_a, _account_b = two_accounts
    original = await insert_fact(
        CareerFact(
            fact="Компетенция уверенная: RAG",
            fact_type="strength",
            source_kind="debrief",
            source_ref="debrief:1",
            confidence=0.75,
            payload={"topic": "rag"},
        ),
        account_id=account_a,
    )

    merged = await merge_fact(
        original.id,
        account_id=account_a,
        fact="Компетенция уверенная: RAG & Memory Management",
        confidence=0.8,
        source_ref="debrief:2",
        recorded_at=None,
        expires_at=original.expires_at,
        payload={"topic": "rag", "level": "confident"},
    )
    assert merged.id == original.id
    assert merged.fact == "Компетенция уверенная: RAG & Memory Management"
    assert merged.confidence == pytest.approx(0.8)
    assert merged.source_ref == "debrief:2"
    assert merged.payload == {"topic": "rag", "level": "confident"}

    still_one = await list_active_facts(account_id=account_a, fact_type="strength")
    assert len(still_one) == 1


async def test_merge_fact_pinned_stays_pinned_when_expires_at_kept_none(two_accounts) -> None:
    account_a, _account_b = two_accounts
    pinned = await insert_fact(
        CareerFact(
            fact="Закреплённый факт", fact_type="note", source_kind="manual", expires_at=None
        ),
        account_id=account_a,
    )

    merged = await merge_fact(
        pinned.id,
        account_id=account_a,
        fact="Обновлённый текст закреплённого факта",
        confidence=0.6,
        source_ref="debrief:3",
        recorded_at=None,
        expires_at=None,  # мердж не срывает закрепление владельца
        payload={},
    )
    assert merged.expires_at is None


async def test_list_active_facts_combined_type_and_source_filter(two_accounts) -> None:
    account_a, _account_b = two_accounts
    await insert_fact(
        CareerFact(fact="A", fact_type="strength", source_kind="debrief"), account_id=account_a
    )
    await insert_fact(
        CareerFact(fact="B", fact_type="strength", source_kind="manual"), account_id=account_a
    )
    await insert_fact(
        CareerFact(fact="C", fact_type="skill_gap", source_kind="debrief"), account_id=account_a
    )

    only_strength = await list_active_facts(account_id=account_a, fact_type="strength")
    assert {f.fact for f in only_strength} == {"A", "B"}

    strength_and_debrief = await list_active_facts(
        account_id=account_a, fact_type="strength", source_kind="debrief"
    )
    assert [f.fact for f in strength_and_debrief] == ["A"]
