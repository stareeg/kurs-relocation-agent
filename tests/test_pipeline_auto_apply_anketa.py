"""Генерация ответов анкеты работодателя (Фаза 3.2, auto_apply_roadmap_2026_08_17.md) —
тот же паттерн ремонта, что у сопроводительного (test_cover_letter_style_repair.py), плюс
сопоставление choice-ответов модели с реальными label вариантов."""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import AnketaOption, AnketaQuestion
from core.domains.pipeline.auto_apply import anketa as anketa_module
from core.domains.pipeline.auto_apply.anketa import _AnketaAnswerBatch, generate_anketa_answers
from core.domains.preparation.asker import record_from_request_fallback
from core.domains.preparation.models import VacancyRecord
from tests.fakes import FakeLlm, RaisingLlm, use_fake_llm


def _record() -> VacancyRecord:
    return record_from_request_fallback(
        "1",
        vacancy_text="Нужен инженер на Python/FastAPI/Kafka, отклик через анкету.",
        title="Python разработчик",
        company="Acme",
    )


def _stub_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anketa_module, "load_resume", lambda data=None: "РЕЗЮМЕ")
    monkeypatch.setattr(anketa_module, "load_candidate_identity", lambda data=None: "Кандидат")


def _text_question(qid: str = "q1") -> AnketaQuestion:
    return AnketaQuestion(id=qid, text="Опишите пример задачи.", type="text")


def _single_choice_question(qid: str = "q2") -> AnketaQuestion:
    return AnketaQuestion(
        id=qid,
        text="Опыт с Python?",
        type="single_choice",
        options=[
            AnketaOption(id="100", label="Менее 3 лет"),
            AnketaOption(id="101", label="3-5 лет"),
            AnketaOption(id="102", label="Более 5 лет"),
        ],
    )


def _multi_choice_question(qid: str = "q3") -> AnketaQuestion:
    return AnketaQuestion(
        id=qid,
        text="Какие пакеты использовали?",
        type="multi_choice",
        options=[
            AnketaOption(id="200", label="FastAPI"),
            AnketaOption(id="201", label="Flask"),
            AnketaOption(id="202", label="Celery"),
        ],
    )


async def test_empty_questions_no_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_llm(monkeypatch, RaisingLlm())
    result = await generate_anketa_answers([], _record(), account_id=1)
    assert result == []


async def test_clean_answers_single_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch)
    questions = [_text_question(), _single_choice_question(), _multi_choice_question()]

    def on_structured(feature: str, *, schema: type, **kwargs):
        assert feature == "anketa_answer"
        assert schema is _AnketaAnswerBatch
        return _AnketaAnswerBatch(
            answers=[
                {
                    "question_id": "q1",
                    "answer": "Собрал сервис на FastAPI, снизил задержку на 40 процентов.",
                },
                {"question_id": "q2", "answer": "3-5 лет"},
                {"question_id": "q3", "answer": "FastAPI; Celery"},
            ]
        )

    llm = use_fake_llm(monkeypatch, FakeLlm(on_structured=on_structured))
    answers = await generate_anketa_answers(questions, _record(), account_id=1)

    assert len(llm.calls) == 1
    by_id = {a.question_id: a.value for a in answers}
    assert by_id["q1"] == "Собрал сервис на FastAPI, снизил задержку на 40 процентов."
    assert by_id["q2"] == "3-5 лет"
    assert by_id["q3"] == "FastAPI; Celery"


async def test_unmatched_choice_resolves_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch)
    questions = [_single_choice_question()]

    def on_structured(feature: str, *, schema: type, **kwargs):
        return _AnketaAnswerBatch(answers=[{"question_id": "q2", "answer": "Никогда не пробовал"}])

    use_fake_llm(monkeypatch, FakeLlm(on_structured=on_structured))
    answers = await generate_anketa_answers(questions, _record(), account_id=1)
    assert answers[0].value == ""


async def test_repairs_once_on_style_violations(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch)
    questions = [_text_question()]
    dirty = "В заключение хочу отметить: обладаю глубокой экспертизой в Python."
    clean = "Собрал сервис на FastAPI, снизил задержку на 40%."
    calls: list[str] = []

    def on_structured(feature: str, *, schema: type, **kwargs):
        calls.append(kwargs["user"])
        answer = dirty if len(calls) == 1 else clean
        return _AnketaAnswerBatch(answers=[{"question_id": "q1", "answer": answer}])

    use_fake_llm(monkeypatch, FakeLlm(on_structured=on_structured))
    answers = await generate_anketa_answers(questions, _record(), account_id=1)

    assert len(calls) == 2
    assert "Нарушения стиля" in calls[1]
    assert answers[0].value == clean


async def test_repair_failure_falls_back_to_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resume(monkeypatch)
    questions = [_text_question()]
    dirty = "В заключение хочу отметить: обладаю глубокой экспертизой."
    calls: list[str] = []

    def on_structured(feature: str, *, schema: type, **kwargs):
        calls.append(kwargs["user"])
        if len(calls) == 1:
            return _AnketaAnswerBatch(answers=[{"question_id": "q1", "answer": dirty}])
        return _AnketaAnswerBatch(answers=[])  # -> LlmError("пустой список ответов анкеты")

    use_fake_llm(monkeypatch, FakeLlm(on_structured=on_structured))
    answers = await generate_anketa_answers(questions, _record(), account_id=1)

    assert len(calls) == 2
    assert answers[0].value == dirty


async def test_answers_use_requesting_account_resume_not_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ответы анкеты строятся на резюме ЗАПРОСИВШЕГО аккаунта — не на чужом (уходят в реальную
    форму hh.ru). Тот же класс бага, что у сопроводительного, 2026-08-26."""
    import core.domains.profile.structured_store as structured_store

    resume_by_account = {7: {"marker": "РЕЗЮМЕ-АЛИСЫ"}, 9: {"marker": "РЕЗЮМЕ-БОБА"}}

    async def fake_read(account_id: int):
        return resume_by_account[account_id]

    monkeypatch.setattr(structured_store, "read_resume_data_for_account", fake_read)
    # Эхо-заглушки: маркер резюме аккаунта дословно попадает в системный промпт.
    monkeypatch.setattr(anketa_module, "load_resume", lambda data=None: (data or {}).get("marker", ""))
    monkeypatch.setattr(
        anketa_module, "load_candidate_identity", lambda data=None: (data or {}).get("marker", "")
    )

    seen_system: list[str] = []

    def on_structured(feature: str, *, schema: type, **kwargs):
        seen_system.append(kwargs["system"])
        return _AnketaAnswerBatch(answers=[{"question_id": "q1", "answer": "Пример задачи."}])

    use_fake_llm(monkeypatch, FakeLlm(on_structured=on_structured))
    await generate_anketa_answers([_text_question()], _record(), account_id=7)

    assert "РЕЗЮМЕ-АЛИСЫ" in seen_system[0]
    assert "РЕЗЮМЕ-БОБА" not in seen_system[0]
