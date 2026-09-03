"""Юниты на дедуп доп. пачки вопросов скрининга (без LLM/БД)."""

from __future__ import annotations

from core.domains.preparation.screening.questions import (
    HrQuestion,
    QuestionGroup,
    ScreeningQuestion,
    _filter_new_groups,
    _filter_new_hr,
    _norm_question,
)


def test_norm_question_collapses_case_and_space() -> None:
    assert _norm_question("  Почему  Уходите? ") == "почему уходите?"


def test_filter_new_hr_skips_duplicates() -> None:
    existing = {_norm_question("Почему уходите?")}
    items = [
        HrQuestion(question="Почему уходите?", intent="x", draft_answer="a"),
        HrQuestion(question="Почему эта роль?", intent="y", draft_answer="b"),
    ]
    out = _filter_new_hr(items, existing)
    assert [q.question for q in out] == ["Почему эта роль?"]


def test_filter_new_groups_drops_empty_after_dedup() -> None:
    existing = {_norm_question("Чем заменяете?")}
    groups = [
        QuestionGroup(
            title="Текучка",
            hook="замена",
            questions=[
                ScreeningQuestion(question="Чем заменяете?", probe="a", expect="b"),
                ScreeningQuestion(question="Кто в команде?", probe="c", expect="d"),
            ],
        ),
        QuestionGroup(
            title="Только дубль",
            hook="x",
            questions=[ScreeningQuestion(question="Чем заменяете?", probe="a", expect="b")],
        ),
    ]
    out = _filter_new_groups(groups, existing)
    assert len(out) == 1
    assert out[0].title == "Текучка"
    assert [q.question for q in out[0].questions] == ["Кто в команде?"]
