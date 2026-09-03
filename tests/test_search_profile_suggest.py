"""Тесты подбора профиля поиска: ротация вариантов и один повтор при исчерпании.

Контекст — plans/scoring_precision_2026_08_17.md §2 (Этап 0). Баг был в том, что панель
присылала в `exclude_priorities` только ВЫБРАННОЕ, вход запроса между нажатиями не менялся и
`call.run` отдавал ответ из result-кэша. Здесь фиксируем серверную часть контракта: исключения
реально доходят до промпта, а если модель всё равно вернула почти только старое — делается
ровно один повтор.
"""

from __future__ import annotations

import logging

import pytest

from core.domains.profile import search_profile_suggest as mod
from core.domains.profile.model import DesiredPosition, ResumeData, SearchCriteria
from core.domains.profile.search_profile_suggest import (
    MIN_FRESH_PRIORITIES,
    PrioritySuggestion,
    SearchProfileSuggestion,
    suggest_search_profile,
)
from core.kernel import ports
from tests.fakes import FakeLlm


def _resume() -> ResumeData:
    return ResumeData(
        position=DesiredPosition(title="Lead LLM Engineer", grade=["Senior", "Lead"]),
        search_criteria=SearchCriteria(),
        key_skills=["Python", "LLM", "RAG"],
    )


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "get_settings", lambda: type("S", (), {"openrouter_api_key": "k"})())

    async def _read(_account_id: int) -> ResumeData:
        return _resume()

    monkeypatch.setattr(mod, "read_resume_data_for_account", _read)


def _slate(*labels: str, role_kind: str = "", market: str = "") -> SearchProfileSuggestion:
    return SearchProfileSuggestion(
        role_kind=role_kind,
        market_segment=market,
        priorities=[PrioritySuggestion(label=lb, reason="из навыков") for lb in labels],
    )


async def test_exclude_reaches_prompt() -> None:
    """Исключения обязаны попасть в текст запроса — от него зависит ключ result-кэша."""
    llm = FakeLlm(result=_slate("Agentic AI", "AI Safety", "MLOps"))

    with ports.use_ports(llm=llm):
        await suggest_search_profile(account_id=1, exclude_priorities=["LLM & RAG", "  "])

    user = llm.calls[0]["user"]
    assert "LLM & RAG" in user
    assert "Exclude" in user


async def test_no_exclude_no_exclude_block() -> None:
    llm = FakeLlm(result=_slate("Agentic AI", "AI Safety", "MLOps"))

    with ports.use_ports(llm=llm):
        await suggest_search_profile(account_id=1)

    assert "Exclude" not in llm.calls[0]["user"]


async def test_excluded_labels_filtered_from_result() -> None:
    """Модель повторила исключённое — на выход оно не проходит."""
    llm = FakeLlm(result=_slate("LLM & RAG", "Agentic AI", "AI Safety", "MLOps"))

    with ports.use_ports(llm=llm):
        got = await suggest_search_profile(account_id=1, exclude_priorities=["llm & rag"])

    assert [p.label for p in got.priorities] == ["Agentic AI", "AI Safety", "MLOps"]


async def test_retry_when_almost_everything_was_excluded(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Новых пунктов меньше порога → ровно один повтор, результаты складываются."""
    first = _slate("LLM & RAG", "MLOps", "Agentic AI")  # 2 из 3 в exclude → 1 новый
    second = _slate("AI Safety", "Multi-agent systems", "MLOps")  # MLOps уже взят

    llm = FakeLlm(results=[first, second])
    with caplog.at_level(logging.INFO, logger="core.domains.profile.search_profile_suggest"):
        with ports.use_ports(llm=llm):
            got = await suggest_search_profile(
                account_id=1, exclude_priorities=["LLM & RAG", "Agentic AI"]
            )

    assert len(llm.calls) == 2, "повтор должен быть ровно один"
    assert [p.label for p in got.priorities] == [
        "MLOps",
        "AI Safety",
        "Multi-agent systems",
    ]
    assert "усиленной инструкцией" in caplog.text


async def test_retry_prompt_differs_from_first() -> None:
    """Повтор обязан отличаться текстом — иначе он вернул бы закэшированный первый ответ."""
    llm = FakeLlm(results=[_slate("MLOps"), _slate("AI Safety", "RAG")])

    with ports.use_ports(llm=llm):
        await suggest_search_profile(account_id=1, exclude_priorities=["LLM & RAG"])

    first_user = llm.calls[0]["user"]
    retry_user = llm.calls[1]["user"]
    assert retry_user != first_user
    assert "ВНИМАНИЕ" in retry_user


async def test_no_retry_when_enough_fresh() -> None:
    llm = FakeLlm(results=[_slate("A", "B", "C", "D")])

    with ports.use_ports(llm=llm):
        got = await suggest_search_profile(account_id=1, exclude_priorities=["LLM & RAG"])

    assert len(llm.calls) == 1
    assert len(got.priorities) >= MIN_FRESH_PRIORITIES


async def test_no_retry_when_nothing_was_excluded() -> None:
    """Первое нажатие: исключать нечего, скудный ответ — не повод жечь второй вызов."""
    llm = FakeLlm(results=[_slate("MLOps")])

    with ports.use_ports(llm=llm):
        got = await suggest_search_profile(account_id=1)

    assert len(llm.calls) == 1
    assert [p.label for p in got.priorities] == ["MLOps"]


async def test_retry_fills_empty_profile_axes_only() -> None:
    """Оси профиля от exclude не зависят: пустые добираем из повтора, заполненные не трогаем."""
    first = _slate("MLOps", role_kind="Делаю руками", market="")
    second = _slate("AI Safety", "RAG", role_kind="Управляю людьми", market="IT")

    llm = FakeLlm(results=[first, second])
    with ports.use_ports(llm=llm):
        got = await suggest_search_profile(account_id=1, exclude_priorities=["LLM & RAG"])

    assert got.role_kind == "Делаю руками", "ответ первого вызова не перетирается повтором"
    assert got.market_segment == "IT", "пустая ось добирается из повтора"


async def test_empty_resume_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _empty(_account_id: int) -> ResumeData:
        return ResumeData()

    monkeypatch.setattr(mod, "read_resume_data_for_account", _empty)
    llm = FakeLlm(result=_slate("MLOps"))

    with ports.use_ports(llm=llm):
        with pytest.raises(ValueError):
            await suggest_search_profile(account_id=1)

    assert llm.calls == [], "на пустом резюме LLM звать не надо"
