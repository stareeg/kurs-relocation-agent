"""План 2026-07-23, шаг 7 + доп. усиление надёжности (после живой проверки шага 16): часть A
(вопросы HR→кандидату) и часть B (группы вопросов кандидат→HR) генерируются двумя независимыми
LLM-вызовами `core/screening/questions.py`. Часть A прогоняется через `lint_spoken_text` и, при
нарушениях устного стиля в `draft_answer`, чинится ровно одним ремонтным вызовом - тем же
паттерном, что `core/screening/pitch.py` использует для легенды."""

from __future__ import annotations

import json

import pytest

from core.kernel.errors import LlmError
from core.domains.preparation.screening import questions as questions_module
from core.domains.preparation.screening.brief import JdBrief
from core.domains.preparation.screening.questions import ScreeningQuestions, generate_screening_questions
from tests.fakes import FakeLlm, use_fake_llm


def _brief() -> JdBrief:
    return JdBrief(role_reality="Строить сервисы автоматизации")


async def _async_result(value):
    return value


def _patch_settings_and_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        questions_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": "test"})()
    )
    monkeypatch.setattr(
        questions_module, "_load_hr_questions_prompt", lambda **_: _async_result("SYSTEM_HR")
    )
    monkeypatch.setattr(
        questions_module, "_load_groups_prompt", lambda **_: _async_result("SYSTEM_GROUPS")
    )


_CLEAN_HR = json.dumps(
    {
        "hr_questions": [
            {
                "question": "Расскажите про опыт с автоматизацией",
                "intent": "проверяют глубину",
                "draft_answer": "Собирал сервис, который считает отчёт за пятнадцать минут.",
            }
        ]
    },
    ensure_ascii=False,
)

_DIRTY_HR = json.dumps(
    {
        "hr_questions": [
            {
                "question": "Расскажите про опыт с автоматизацией",
                "intent": "проверяют глубину",
                "draft_answer": "Строил observability и guardrails: это моя основная зона.",
            }
        ]
    },
    ensure_ascii=False,
)

_GROUPS = json.dumps(
    {
        "groups": [
            {
                "title": "Формат работы",
                "hook": "гибридный график",
                "questions": [{"question": "Сколько дней в офисе?", "probe": "реальный формат"}],
            }
        ]
    },
    ensure_ascii=False,
)


async def test_generate_screening_questions_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        questions_module, "get_settings", lambda: type("S", (), {"openrouter_api_key": ""})()
    )
    with pytest.raises(Exception, match="OPENROUTER_API_KEY"):
        await generate_screening_questions(account_id=1, brief=_brief())


async def test_generate_screening_questions_runs_two_independent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        calls.append(str(feature))
        return _CLEAN_HR if system == "SYSTEM_HR" else _GROUPS

    _patch_settings_and_prompts(monkeypatch)
    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_questions(account_id=1, brief=_brief())
    assert isinstance(result, ScreeningQuestions)
    assert len(calls) == 2
    assert all(agent == "screening_questions" for agent in calls)
    assert result.hr_questions[0].question.startswith("Расскажите")
    assert result.groups[0].title == "Формат работы"


async def test_generate_screening_questions_repairs_hr_answer_once_on_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hr_calls: list[str] = []

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        if system == "SYSTEM_HR":
            hr_calls.append(user)
            return _DIRTY_HR if len(hr_calls) == 1 else _CLEAN_HR
        return _GROUPS

    _patch_settings_and_prompts(monkeypatch)
    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_questions(account_id=1, brief=_brief())
    assert len(hr_calls) == 2
    assert "Нарушения устного стиля" in hr_calls[1]
    assert "observability" not in result.hr_questions[0].draft_answer
    assert "guardrails" not in result.hr_questions[0].draft_answer


async def test_generate_screening_questions_no_repair_when_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hr_calls = 0

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        nonlocal hr_calls
        if system == "SYSTEM_HR":
            hr_calls += 1
            return _CLEAN_HR
        return _GROUPS

    _patch_settings_and_prompts(monkeypatch)
    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    await generate_screening_questions(account_id=1, brief=_brief())
    assert hr_calls == 1


async def test_generate_screening_questions_degrades_when_groups_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Часть B упала (битый JSON) - часть A всё равно возвращается, а не пропадает вместе с ней
    (живая проверка шага 16: раньше одна общая схема на обе части роняла их разом)."""

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        return _CLEAN_HR if system == "SYSTEM_HR" else "не json"

    _patch_settings_and_prompts(monkeypatch)
    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_questions(account_id=1, brief=_brief())
    assert result.hr_questions
    assert result.groups == []


async def test_generate_screening_questions_raises_when_both_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        return "не json"

    _patch_settings_and_prompts(monkeypatch)
    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    with pytest.raises(LlmError):
        await generate_screening_questions(account_id=1, brief=_brief())


async def test_generate_screening_questions_hr_repair_failure_falls_back_to_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сам ремонтный вызов части A упал (сеть/битый JSON) - возвращаем черновик до ремонта, а не
    роняем все вопросы HR целиком (см. аналогичный фолбэк в `core/screening/pitch.py`)."""
    hr_calls = 0

    async def fake_complete_text(feature: str, *, system: str, user: str, **kwargs) -> str:
        nonlocal hr_calls
        if system == "SYSTEM_HR":
            hr_calls += 1
            return _DIRTY_HR if hr_calls == 1 else "не json"
        return _GROUPS

    _patch_settings_and_prompts(monkeypatch)
    use_fake_llm(monkeypatch, FakeLlm(on_complete=fake_complete_text))

    result = await generate_screening_questions(account_id=1, brief=_brief())
    assert hr_calls == 2
    assert "guardrails" in result.hr_questions[0].draft_answer
