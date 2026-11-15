"""Контракты и исполнение инструментов агента (ДЗ1): валидация, права, подтверждение, сбои."""

from __future__ import annotations

from collections import deque

import pytest

from agent.contracts import ConfirmationCard, ToolCall, ToolContext
from agent.tools import execute_tool

NOTE = (
    "Здравствуйте! Меня заинтересовала вакансия: 6 лет опыта в backend, Python и Go, "
    "готов к B2B-контракту и переезду."
)


def call(name: str, args: dict | str, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args)


def test_search_filters_and_caps_result_size() -> None:
    result, error, _ = execute_tool(
        call("search_vacancies", {"role": "backend", "country": "Польша"}), ToolContext()
    )
    assert error is None
    assert result["total"] == 2
    assert result["shown"] == 2
    assert all(item["country"] == "Польша" for item in result["items"])


def test_search_returns_hint_when_nothing_found() -> None:
    result, error, _ = execute_tool(
        call("search_vacancies", {"role": "backend", "min_salary_eur": 10_000}), ToolContext()
    )
    assert error is None
    assert result["items"] == []
    assert "ослабьте фильтры" in result["hint"]


def test_search_rejects_out_of_range_salary_as_data() -> None:
    result, error, _ = execute_tool(
        call("search_vacancies", {"role": "backend", "min_salary_eur": 99_999}), ToolContext()
    )
    assert error is not None
    assert error.type == "validation"
    assert "min_salary_eur" in error.message
    assert result["error"]["hint"]


def test_client_scoped_fields_come_from_session_not_from_model() -> None:
    result, error, _ = execute_tool(
        call("country_rules", {"country": "Сербия"}),
        ToolContext(citizenship="RU", applicant_id="acc_7"),
    )
    assert error is None
    assert result["citizenship"] == "RU"
    assert result["country"] == "Сербия"


def test_unknown_tool_is_reported_with_allowed_names() -> None:
    result, error, _ = execute_tool(call("drop_database", {}), ToolContext())
    assert error is not None
    assert error.type == "not_found"
    assert "search_vacancies" in error.hint
    assert result["error"]["type"] == "not_found"


def test_action_is_not_executed_without_confirmation() -> None:
    context = ToolContext(confirm=lambda card: False)
    result, error, confirmed_by = execute_tool(
        call("submit_application", {"vacancy_id": "v01", "cover_note": NOTE}), context
    )
    assert error is None
    assert confirmed_by is None
    assert result["cancelled"] is True
    assert context.submissions == {}


def test_action_runs_after_confirmation_and_is_idempotent() -> None:
    cards: list[ConfirmationCard] = []
    context = ToolContext(confirm=lambda card: cards.append(card) or True)
    payload = call("submit_application", {"vacancy_id": "v01", "cover_note": NOTE})

    first, error, confirmed_by = execute_tool(payload, context)
    second, error2, _ = execute_tool(payload, context)

    assert error is None and error2 is None
    assert confirmed_by == context.applicant_id
    assert first["queued"] is True
    assert second["idempotent_replay"] is True
    assert second["submission_id"] == first["submission_id"]
    # Человек подтверждает конкретные параметры, а не фразу модели.
    assert cards[0].params["vacancy_id"] == "v01"


def test_read_retries_twice_then_returns_timeout_as_data() -> None:
    context = ToolContext(faults={"search_vacancies": deque(["timeout", "timeout"])})
    result, error, _ = execute_tool(
        call("search_vacancies", {"role": "backend"}), context
    )
    assert error is not None
    assert error.type == "timeout"
    assert result["error"]["hint"]
    assert context.faults["search_vacancies"] == deque()


def test_read_recovers_after_single_fault() -> None:
    context = ToolContext(faults={"search_vacancies": deque(["timeout"])})
    result, error, _ = execute_tool(call("search_vacancies", {"role": "backend"}), context)
    assert error is None
    assert result["total"] >= 1


def test_action_has_no_automatic_retry() -> None:
    context = ToolContext(confirm=lambda card: True, faults={"submit_application": deque(["timeout"])})
    result, error, _ = execute_tool(
        call("submit_application", {"vacancy_id": "v01", "cover_note": NOTE}), context
    )
    assert error is not None
    assert error.type == "timeout"
    assert "идемпотентности" in error.hint
    assert result["error"]["type"] == "timeout"


def test_broken_json_arguments_are_returned_to_model() -> None:
    result, error, _ = execute_tool(call("search_vacancies", "{role: backend"), ToolContext())
    assert error is not None
    assert error.type == "validation"
    assert "JSON" in error.message
    assert result["error"]["type"] == "validation"


@pytest.mark.parametrize("bad_id", ["v1", "01", "vacancy-1", ""])
def test_submit_rejects_wrong_vacancy_id(bad_id: str) -> None:
    context = ToolContext(confirm=lambda card: True)
    _, error, _ = execute_tool(
        call("submit_application", {"vacancy_id": bad_id, "cover_note": NOTE}), context
    )
    assert error is not None
    assert error.type == "validation"