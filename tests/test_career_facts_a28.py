"""A-28: career_facts — из разбора в долгую память → контекст следующей подготовки."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.domains.career.facts import (
    extract_facts_from_debrief_analysis,
    persist_facts,
    record_facts_from_debrief,
    render_facts_block,
)
from core.domains.career.models import CareerFact
from core.domains.preparation.debrief import DebriefRecord
from core.domains.preparation.interview.prep_context import PrepContext, gather_prep_context
from core.kernel.events import InterviewDebriefed
from core.kernel.ids import VacancyId

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "core" / "platform" / "db" / "migrations"


def test_migration_defines_career_facts() -> None:
    sql = (MIGRATIONS / "0074_career_facts.sql").read_text(encoding="utf-8")
    assert "create table career_facts" in sql
    assert "confidence" in sql
    assert "expires_at" in sql
    assert "source_kind" in sql
    assert "'debrief'" in sql


def test_extract_facts_from_debrief_analysis() -> None:
    facts = extract_facts_from_debrief_analysis(
        {
            "topics_to_study": ["LangGraph checkpoints", "RAG eval"],
            "strong_answers": ["Рассказал про multi-agent в ПРОМ"],
            "weak_answers": [
                {
                    "question": "Как меряешь faithfulness?",
                    "how_to_improve": "Назвать конкретные метрики и пороги",
                }
            ],
            "competency_map": [
                {"topic": "FastAPI", "level": "confident"},
                {"topic": "KV-cache", "level": "weak"},
            ],
            "summary": "В целом ок, просели на eval.",
        },
        vacancy_id="hh-99",
        stage="theory",
        debrief_id=42,
    )
    assert facts
    assert all(f.source_kind == "debrief" for f in facts)
    assert all(f.source_ref == "debrief:42" for f in facts)
    assert all(f.expires_at is not None for f in facts)
    texts = " ".join(f.fact for f in facts)
    assert "LangGraph" in texts
    assert "multi-agent" in texts
    assert "faithfulness" in texts or "метрик" in texts
    assert "FastAPI" in texts
    assert "KV-cache" in texts
    types = {f.fact_type for f in facts}
    assert "skill_gap" in types
    assert "strength" in types


def test_extract_dedupes_and_caps() -> None:
    facts = extract_facts_from_debrief_analysis(
        {
            "topics_to_study": ["X", "X", "Y"],
            "strong_answers": [],
            "weak_answers": [],
        },
        vacancy_id="v",
        debrief_id=1,
    )
    assert len([f for f in facts if "Подтянуть: X" in f.fact]) == 1


def test_render_facts_block_empty() -> None:
    assert render_facts_block([]) == ""


def test_render_facts_block_lists_types() -> None:
    block = render_facts_block(
        [
            CareerFact(
                fact="Подтянуть: RAG eval",
                fact_type="skill_gap",
                source_kind="debrief",
                confidence=0.75,
            )
        ]
    )
    assert "пробел" in block
    assert "RAG eval" in block
    assert "75%" in block


async def test_record_facts_from_debrief_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    record = DebriefRecord(
        id=7,
        vacancy_id="gm_1",
        stage="theory",
        summary="",
        analysis={"topics_to_study": ["tool calling"], "strong_answers": ["Агенты"]},
        created_at=datetime.now(UTC),
    )
    monkeypatch.setattr(
        "core.domains.preparation.debrief.get_debrief",
        AsyncMock(return_value=record),
    )
    saved: list[CareerFact] = []

    async def _insert(fact: CareerFact, *, account_id=None, db=None) -> CareerFact:
        saved.append(fact)
        return fact.model_copy(update={"id": len(saved)})

    monkeypatch.setattr("core.domains.career.facts.insert_fact", _insert)
    # Нет активных фактов — мердж-проверка (Этап 4.1) не находит кандидата, вставка как раньше.
    monkeypatch.setattr(
        "core.domains.career.facts.list_active_facts", AsyncMock(return_value=[])
    )

    out = await record_facts_from_debrief(
        InterviewDebriefed(
            vacancy_id=VacancyId("gm_1"),
            stage="theory",
            debrief_id=7,
            account_id=1,
        ),
        account_id=1,
    )
    assert len(out) >= 2
    assert saved
    assert all(f.source_kind == "debrief" for f in saved)


async def test_persist_facts_merges_same_type_and_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Этап 4.1: второй разбор с тем же fact_type+topic обновляет активный факт, не дублирует."""
    existing = CareerFact(
        id=11,
        fact="Компетенция уверенная: RAG",
        fact_type="strength",
        source_kind="debrief",
        source_ref="debrief:1",
        confidence=0.75,
        payload={"topic": "rag", "level": "confident"},
    )
    monkeypatch.setattr(
        "core.domains.career.facts.list_active_facts", AsyncMock(return_value=[existing])
    )
    merge_calls: list[dict] = []

    async def _merge(fact_id, *, account_id, fact, confidence, source_ref, recorded_at, expires_at, payload, db=None):
        merge_calls.append({"fact_id": fact_id, "fact": fact, "confidence": confidence})
        return existing.model_copy(update={"fact": fact, "confidence": confidence})

    insert_calls: list[CareerFact] = []

    async def _insert(fact: CareerFact, *, account_id=None, db=None) -> CareerFact:
        insert_calls.append(fact)
        return fact.model_copy(update={"id": 99})

    monkeypatch.setattr("core.domains.career.facts.merge_fact", _merge)
    monkeypatch.setattr("core.domains.career.facts.insert_fact", _insert)

    new_fact = CareerFact(
        fact="Компетенция уверенная: RAG & Memory Management",
        fact_type="strength",
        source_kind="debrief",
        source_ref="debrief:2",
        confidence=0.8,
        payload={"topic": "rag", "level": "confident"},
    )
    out = await persist_facts([new_fact], account_id=1)

    assert len(out) == 1
    assert not insert_calls  # не создана вторая строка
    assert merge_calls == [{"fact_id": 11, "fact": "Компетенция уверенная: RAG & Memory Management", "confidence": 0.8}]


async def test_persist_facts_inserts_when_topic_missing_or_new(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.domains.career.facts.list_active_facts", AsyncMock(return_value=[]))
    insert_calls: list[CareerFact] = []

    async def _insert(fact: CareerFact, *, account_id=None, db=None) -> CareerFact:
        insert_calls.append(fact)
        return fact.model_copy(update={"id": len(insert_calls)})

    async def _merge(*_a, **_k):
        raise AssertionError("merge_fact не должен звонить без кандидата")

    monkeypatch.setattr("core.domains.career.facts.insert_fact", _insert)
    monkeypatch.setattr("core.domains.career.facts.merge_fact", _merge)

    # Факт без topic (например, из strong_answers/summary) — всегда новая строка.
    no_topic = CareerFact(
        fact="Сильный ответ про архитектуру",
        fact_type="strength",
        source_kind="debrief",
        confidence=0.8,
        payload={},
    )
    out = await persist_facts([no_topic], account_id=1)
    assert len(out) == 1
    assert len(insert_calls) == 1


async def test_debrief_fact_lands_in_prep_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Приёмка A-28: факт из разбора попадает в контекст следующей подготовки."""
    fact = CareerFact(
        id=1,
        fact="Подтянуть: schema linking в Text2SQL",
        fact_type="skill_gap",
        source_kind="debrief",
        source_ref="debrief:11",
        confidence=0.75,
        recorded_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=90),
    )

    async def _active(*, account_id=None, limit=20, source_kind=None, db=None):
        return [fact]

    monkeypatch.setattr("core.domains.career.repo.list_active_facts", _active)
    monkeypatch.setattr("core.domains.career.facts.list_active_facts", _active)

    # Остальные блоки prep — пустые (нет PG / заглушки).
    async def _empty(*_a, **_k) -> str:
        return ""

    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._next_stage_block", _empty
    )
    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._hr_facts_block", _empty
    )
    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._weak_topics_block", _empty
    )
    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._strong_answers_block", _empty
    )
    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._recruiter_feedback_block",
        _empty,
    )
    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._asked_questions_block", _empty
    )
    monkeypatch.setattr(
        "core.domains.preparation.interview.prep_context._past_sessions_block", _empty
    )

    fake_db = object()
    ctx = await gather_prep_context("hh-next", "theory", account_id=1, db=fake_db)  # type: ignore[arg-type]
    assert isinstance(ctx, PrepContext)
    assert "schema linking" in ctx.career_facts
    rendered = ctx.render()
    assert "Долгая память кандидата" in rendered
    assert "schema linking" in rendered
