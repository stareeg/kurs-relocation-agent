"""L-12: generate_prep_questions через structured, не complete+ручной JSON."""

from __future__ import annotations

import pytest

from core.domains.preparation.interview import prep as prep_mod
from core.domains.preparation.interview.prep import (
    _ANSWER_FOCUS,
    _ASK_THEM_FOCUS,
    _PrepQuestionOut,
    _PrepQuestionsOut,
    _questions_from_structured,
    generate_prep_questions,
)
from core.domains.preparation.interview.prep_context import PrepContext
from core.kernel import ports
from core.domains.preparation.models import VacancyRecord
from tests.fakes import FakeLlm


def _record() -> VacancyRecord:
    # score обязателен в модели, для L-12 не используется глубоко — model_construct.
    return VacancyRecord.model_construct(
        vacancy_id="v-l12",
        title="Lead LLM",
        company="Acme",
        vacancy_text="Нужен опыт RAG, агенты, Python.",
        salary_text="от 450000",
        score=None,
    )


def test_questions_from_structured_normalizes_and_keeps_fields() -> None:
    parsed = _PrepQuestionsOut(
        questions=[
            _PrepQuestionOut(
                category="technical",
                text="Как устроен ваш RAG?",
                hint="Упор на гибридный поиск",
                answer="Два слоя - плоский и графовый.",
            ),
            _PrepQuestionOut(
                category="behavioral",
                text="Расскажи про конфликт в команде",
                hint="",
                answer="Разрулил через явный owner.",
            ),
        ]
    )
    qs = _questions_from_structured(parsed)
    assert len(qs) == 2
    assert qs[0].category == "technical"
    assert qs[0].answer.startswith("Два слоя")
    assert qs[1].category == "behavioral"


@pytest.mark.asyncio
async def test_generate_prep_questions_uses_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    # L-49: generate_prep_questions — Pipeline из двух параллельных structured-вызовов
    # (answers ∥ ask_them, см. _ANSWER_FOCUS/_ASK_THEM_FOCUS) — фейк различает их по фокус-хвосту.
    answers_result = _PrepQuestionsOut(
        questions=[
            _PrepQuestionOut(
                category="case",
                text="Спроектируй агентный пайплайн под нагрузку",
                hint="Trade-off latency vs cost",
                answer="Сначала SLO, потом декомпозиция.",
            )
        ]
    )
    ask_them_result = _PrepQuestionsOut(
        questions=[
            _PrepQuestionOut(
                category="questions_to_ask",
                text="Как устроен онбординг в команде?",
                hint="",
                answer="",
            )
        ]
    )

    def _on_structured(feature: str, *, schema: type, dynamic_tail: str = "", **_kwargs):
        if dynamic_tail.endswith(_ASK_THEM_FOCUS):
            return ask_them_result
        if dynamic_tail.endswith(_ANSWER_FOCUS):
            return answers_result
        raise AssertionError(f"неожиданный dynamic_tail: {dynamic_tail!r}")

    fake = FakeLlm(on_structured=_on_structured)
    monkeypatch.setattr(
        prep_mod,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": "test-key"})(),
    )

    async def _fake_gather(*_a, **_k) -> PrepContext:
        return PrepContext()

    monkeypatch.setattr(prep_mod, "gather_prep_context", _fake_gather)

    with ports.use_ports(llm=fake):
        questions = await generate_prep_questions(_record(), "tech", account_id=1)

    assert len(questions) == 2
    assert {q.category for q in questions} == {"case", "questions_to_ask"}
    assert len(fake.calls) == 2
    for call in fake.calls:
        assert call["feature"] == "prep"
        assert call["schema"] is _PrepQuestionsOut
        assert "system" in call
        assert "user" in call


@pytest.mark.asyncio
async def test_generate_prep_questions_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        prep_mod,
        "get_settings",
        lambda: type("S", (), {"openrouter_api_key": ""})(),
    )
    fake = FakeLlm(result=None)
    with ports.use_ports(llm=fake):
        with pytest.raises(Exception) as exc:
            await generate_prep_questions(_record(), "tech", account_id=1)
    assert "OPENROUTER_API_KEY" in str(exc.value)
    assert fake.calls == []
