"""Unit-тесты `append_prep_questions`: «ещё пачку» из чата дописывается в
`prep_sessions` вместо перезаписи, с дедупом по точному тексту вопроса.

Коллаборатор-функции того же модуля (`load_prep_history`/`save_prep_session`/
`update_prep_session_questions`) подменяются моками — без живого Postgres, как у остальных
тестов репо-слоя в этом проекте.
"""

from __future__ import annotations

import pytest

import core.domains.preparation.prep as prep_repo
from core.domains.preparation.prep import PrepSession, append_prep_questions
from core.domains.preparation.models import PrepQuestion

_Q1 = PrepQuestion(category="technical", text="Как Kafka гарантирует порядок?", hint="", answer="a1")
_Q2 = PrepQuestion(category="technical", text="Чем Flink отличается от Kafka Streams?", hint="", answer="a2")


async def test_append_prep_questions_creates_session_when_none_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved: list[PrepSession] = []

    async def fake_load_history(
        vacancy_id: str, limit: int = 10, *, account_id=None, db=None
    ) -> list[PrepSession]:
        return []

    async def fake_save(session: PrepSession, *, account_id=None, db=None) -> PrepSession:
        session.id = 1
        saved.append(session)
        return session

    monkeypatch.setattr(prep_repo, "load_prep_history", fake_load_history)
    monkeypatch.setattr(prep_repo, "save_prep_session", fake_save)

    result = await append_prep_questions("vac-1", "tech", [_Q1], account_id=1, db=object())

    assert len(saved) == 1
    assert saved[0].vacancy_id == "vac-1"
    assert saved[0].stage == "tech"
    assert [q["text"] for q in saved[0].questions] == [_Q1.text]
    assert result.id == 1


async def test_append_prep_questions_merges_into_existing_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = PrepSession(
        id=7,
        vacancy_id="vac-1",
        stage="tech",
        questions=[{"category": "technical", "text": _Q1.text, "hint": "", "answer": "old"}],
    )

    async def fake_load_history(
        vacancy_id: str, limit: int = 10, *, account_id=None, db=None
    ) -> list[PrepSession]:
        return [existing]

    calls: list[tuple[int, list]] = []

    async def fake_update(prep_id: int, questions: list, *, account_id=None, db=None) -> None:
        calls.append((prep_id, questions))

    monkeypatch.setattr(prep_repo, "load_prep_history", fake_load_history)
    monkeypatch.setattr(prep_repo, "update_prep_session_questions", fake_update)

    result = await append_prep_questions("vac-1", "tech", [_Q1, _Q2], account_id=1, db=object())

    assert len(calls) == 1
    prep_id, merged = calls[0]
    assert prep_id == 7
    # _Q1 - точный дубль существующего текста, не должен продублироваться; _Q2 - новый, добавлен.
    assert [q["text"] for q in merged] == [_Q1.text, _Q2.text]
    assert result.questions == merged


async def test_append_prep_questions_all_duplicates_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = PrepSession(
        id=9,
        vacancy_id="vac-2",
        stage="theory",
        questions=[{"category": "technical", "text": _Q1.text, "hint": "", "answer": "old"}],
    )

    async def fake_load_history(
        vacancy_id: str, limit: int = 10, *, account_id=None, db=None
    ) -> list[PrepSession]:
        return [existing]

    async def fail_update(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        raise AssertionError("update_prep_session_questions не должен звонить при полном дубле")

    monkeypatch.setattr(prep_repo, "load_prep_history", fake_load_history)
    monkeypatch.setattr(prep_repo, "update_prep_session_questions", fail_update)

    result = await append_prep_questions("vac-2", "theory", [_Q1], account_id=1, db=object())

    assert result.questions == existing.questions
