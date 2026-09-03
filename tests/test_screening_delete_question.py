"""Юниты на удаление вопроса из пакета скрининга (без LLM/БД — хранилище замокано)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.preparation.screening import scenarios as sc
from core.domains.preparation.screening_questions import SavedScreeningQuestions


def _saved() -> SavedScreeningQuestions:
    return SavedScreeningQuestions(
        vacancy_id="v1",
        hr_questions=[
            {"question": "Почему уходите?", "intent": "мотив", "draft_answer": "рост"},
            {"question": "Почему эта роль?", "intent": "интерес", "draft_answer": "стек"},
        ],
        groups=[
            {
                "title": "Текучка",
                "hook": "замена",
                "questions": [
                    {"question": "Чем заменяете?", "probe": "a", "expect": "b"},
                    {"question": "Кто в команде?", "probe": "c", "expect": "d"},
                ],
            }
        ],
    )


@pytest.mark.asyncio
async def test_delete_question_hr(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _saved()
    monkeypatch.setattr(
        sc, "get_screening_questions", AsyncMock(return_value=saved)
    )
    captured: dict = {}

    async def fake_merge(vacancy_id, *, account_id, hr_questions=None, groups=None):
        captured["hr"] = hr_questions
        captured["groups"] = groups
        return saved

    monkeypatch.setattr(sc, "merge_screening_questions", fake_merge)

    await sc.delete_question("v1", kind="hr", question="Почему уходите?", account_id=1)
    assert captured["hr"] == [{"question": "Почему эта роль?", "intent": "интерес", "draft_answer": "стек"}]
    assert captured["groups"] is None


@pytest.mark.asyncio
async def test_delete_question_ask_removes_from_group(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _saved()
    monkeypatch.setattr(
        sc, "get_screening_questions", AsyncMock(return_value=saved)
    )
    captured: dict = {}

    async def fake_merge(vacancy_id, *, account_id, hr_questions=None, groups=None):
        captured["hr"] = hr_questions
        captured["groups"] = groups
        return saved

    monkeypatch.setattr(sc, "merge_screening_questions", fake_merge)

    await sc.delete_question("v1", kind="ask", question="Чем заменяете?", account_id=1)
    assert captured["hr"] is None
    assert captured["groups"][0]["questions"] == [
        {"question": "Кто в команде?", "probe": "c", "expect": "d"}
    ]


@pytest.mark.asyncio
async def test_delete_question_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = _saved()
    monkeypatch.setattr(
        sc, "get_screening_questions", AsyncMock(return_value=saved)
    )
    with pytest.raises(Exception):
        await sc.delete_question("v1", kind="hr", question="Нет такого", account_id=1)


@pytest.mark.asyncio
async def test_delete_question_requires_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = SavedScreeningQuestions(vacancy_id="v1")
    monkeypatch.setattr(
        sc, "get_screening_questions", AsyncMock(return_value=empty)
    )
    with pytest.raises(Exception):
        await sc.delete_question("v1", kind="hr", question="Почему уходите?", account_id=1)
