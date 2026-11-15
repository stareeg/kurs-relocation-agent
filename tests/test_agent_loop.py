"""Цикл агента: журнал шагов, лимит шагов, защита от зацикливания, подтверждение действий."""

from __future__ import annotations

from typing import Any

from agent.contracts import ToolCall, ToolContext
from agent.loop import run_agent
from agent.providers import ProviderTurn, ScriptedProvider

NOTE = (
    "Здравствуйте! Меня заинтересовала вакансия: 6 лет опыта в backend, Python и Go, "
    "готов к B2B-контракту и переезду."
)


def test_loop_records_steps_and_returns_final_answer() -> None:
    provider = ScriptedProvider(
        turns=[
            ProviderTurn(
                tool_calls=(ToolCall("c1", "search_vacancies", {"role": "backend"}),),
                tokens_in=100,
                tokens_out=20,
            ),
            ProviderTurn(
                tool_calls=(ToolCall("c2", "country_rules", {"country": "Польша"}),),
                tokens_in=150,
                tokens_out=15,
            ),
            ProviderTurn(content="Готово: вакансии есть, правила проверил.", tokens_in=80),
        ]
    )
    run = run_agent("Найди backend в Польше", provider, max_steps=6)

    assert run.stop_reason == "answered"
    assert [step.tool for step in run.steps] == ["search_vacancies", "country_rules"]
    assert run.answer.startswith("Готово")
    assert run.tokens_in == 330
    assert run.tokens_out == 35
    assert all(step.error is None for step in run.steps)


def test_loop_stops_at_step_limit_and_escalates_to_operator() -> None:
    class AlwaysCalls:
        """Каждый шаг — новый аргумент, поэтому срабатывает лимит шагов, а не защита от повторов."""

        name = "always"
        roles = ("backend", "data", "frontend", "qa")

        def __init__(self) -> None:
            self.step = 0

        def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
            _ = (messages, tools)
            role = self.roles[self.step % len(self.roles)]
            self.step += 1
            return ProviderTurn(tool_calls=(ToolCall("c", "search_vacancies", {"role": role}),))

    run = run_agent("Найди работу", AlwaysCalls(), max_steps=3)

    assert run.stop_reason == "step_limit"
    assert len(run.steps) == 3
    assert "оператору" in (run.answer or "")


def test_loop_guard_stops_third_identical_call_in_a_row() -> None:
    class SameCall:
        name = "same"

        def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
            _ = (messages, tools)
            return ProviderTurn(
                tool_calls=(ToolCall("c", "search_vacancies", {"role": "backend"}),)
            )

    run = run_agent("Найди работу", SameCall(), max_steps=10)

    assert run.stop_reason == "loop_guard"
    assert len(run.steps) == 2
    assert "один и тот же" in (run.answer or "")


def test_action_confirmation_and_cancellation_reach_the_model() -> None:
    provider = ScriptedProvider(
        turns=[
            ProviderTurn(
                tool_calls=(
                    ToolCall(
                        "c1",
                        "submit_application",
                        {"vacancy_id": "v01", "cover_note": NOTE},
                    ),
                )
            ),
            ProviderTurn(content="Отклик не отправлен: вы не подтвердили."),
        ]
    )
    asked: list[bool] = []

    def confirm(_card: Any) -> bool:
        asked.append(True)
        return False

    run = run_agent("Отправь отклик", provider, context=ToolContext(confirm=confirm))

    assert asked == [True]
    assert run.steps[0].result["cancelled"] is True
    assert run.steps[0].confirmed_by is None
    assert run.answer.startswith("Отклик не отправлен")


def test_tool_error_is_visible_in_trace_and_does_not_break_the_loop() -> None:
    provider = ScriptedProvider(
        turns=[
            ProviderTurn(
                tool_calls=(ToolCall("c1", "search_vacancies", {"role": "backend"}),)
            ),
            ProviderTurn(content="Сервис недоступен, данных нет."),
        ]
    )
    from collections import deque

    run = run_agent(
        "Найди работу",
        provider,
        context=ToolContext(faults={"search_vacancies": deque(["timeout", "timeout"])}),
    )

    assert run.stop_reason == "answered"
    assert run.steps[0].error is not None
    assert run.steps[0].error.type == "timeout"
    assert run.answer == "Сервис недоступен, данных нет."