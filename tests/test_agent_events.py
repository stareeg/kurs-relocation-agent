"""A-3 события запуска: наблюдатель получает полный поток узловых событий.

Живых моделей нет: тот же сценарий, что в test_agent_graph, но граф собирается с
наблюдателем-собирателем — проверяем состав и порядок событий (plan_created →
step_started → tool_called → observation → … → done-путь), а также таймеры узлов
(`node_timing`, метрика p90 шага — OQ-29).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from core.app.agent.contracts import ToolContext
from core.app.agent.events import AgentEvent
from core.app.agent.graph import AgentDeps, build_agent_graph, run_agent_goal
from core.app.agent.tools import TOOLS, ensure_tools_registered
from tests.fakes import FakeDemoDb, ScriptedChatModel

ensure_tools_registered()

GOAL = "Найди вакансию backend в Польше и скажи, какие условия въезда"


class EventCollector:
    """Тестовый наблюдатель: копит события в порядке прихода."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def of_type(self, event_type: str) -> list[AgentEvent]:
        return [e for e in self.events if e.type == event_type]


def _plan_spec(*steps: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "steps": [
            {"id": sid, "title": title, "done_criteria": criteria} for sid, title, criteria in steps
        ],
        "note": "цель понята",
    }


def _deps(collector: EventCollector) -> AgentDeps:
    planner = ScriptedChatModel(
        responses=[
            AIMessage(
                content=json.dumps(
                    _plan_spec(
                        ("s1", "Найти вакансии backend", "список вакансий из поиска"),
                        ("s2", "Проверить условия найма", "условия с цитатами"),
                    )
                )
            )
        ]
    )
    executor = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "search_vacancies", "args": {"query": "kestrel"}, "id": "c1"}],
            ),
            AIMessage(content="Нашёл вакансию Applied AI Engineer в Kestrel Analytics."),
        ]
    )
    replanner = ScriptedChatModel(
        responses=[
            AIMessage(
                content=json.dumps(
                    {
                        "action": "continue",
                        "reason": "шаг закрыт",
                        "steps": [
                            {
                                "id": "s1",
                                "title": "Найти вакансии backend",
                                "done_criteria": "список вакансий из поиска",
                                "status": "done",
                            },
                            {
                                "id": "s2",
                                "title": "Проверить условия найма",
                                "done_criteria": "условия",
                                "status": "todo",
                            },
                        ],
                    }
                )
            ),
            AIMessage(
                content=json.dumps({"action": "finish", "reason": "условия названы", "steps": []})
            ),
        ]
    )
    return AgentDeps(
        planner=planner,
        executor=executor,
        replanner=replanner,
        tools=TOOLS,
        tool_context=ToolContext(account_id=1, db=FakeDemoDb()),
        observer=collector,
    )


async def test_observer_receives_full_event_flow():
    """Счастливый путь: план → шаг → инструменты → наблюдения → перестройки, таймеры на каждом узле."""
    collector = EventCollector()
    state = await run_agent_goal(GOAL, deps=_deps(collector))
    assert state["stop_reason"] == "answered"

    types = collector.types()
    assert types[0] == "run_started" or "plan_created" in types
    assert types.count("plan_created") >= 1, "план отдаётся событием"
    assert types.count("step_started") == 2, "два шага — два события старта"
    assert types.count("observation") >= 2, "каждый шаг отдаёт наблюдение"
    assert "tool_called" in types, "вызовы инструментов отдаются событиями"
    assert "step_checked" in types, "чек шага отдаётся событием"
    assert "plan_changed" in types, "перестройка отдаёт событие"
    assert "done" not in types, "done пишет менеджер запусков, а не граф"

    tool = next(e for e in collector.of_type("tool_called"))
    assert tool.payload["tool"] == "search_vacancies"
    assert tool.payload["ok"] is True
    assert tool.payload["step_id"] == "s1"

    started = collector.of_type("step_started")
    assert [e.payload["step_id"] for e in started] == ["s1", "s2"]
    assert started[0].payload["index"] == 1

    plan_created = collector.of_type("plan_created")[0]
    assert [s["id"] for s in plan_created.payload["plan"]] == ["s1", "s2"]


async def test_node_timings_present_for_every_node():
    """Таймеры узлов (OQ-29): у каждого узла есть node_timing, у шага — длительность."""
    collector = EventCollector()
    await run_agent_goal(GOAL, deps=_deps(collector))
    timings = {e.node: e.duration_ms for e in collector.of_type("node_timing")}
    assert {"plan", "step", "check", "replan"} <= set(timings), f"таймеры: {sorted(timings)}"
    step_time = timings.get("step")
    assert step_time is not None and step_time >= 0


async def test_checkpointer_pass_keeps_observer_events():
    """С чекпойнтером события тоже идут (тот же наблюдатель), шаги работают как обычно."""
    collector = EventCollector()
    graph = build_agent_graph(_deps(collector), checkpointer=MemorySaver())
    await graph.ainvoke({"goal": GOAL}, config={"configurable": {"thread_id": "t-events"}})
    assert "plan_created" in collector.types()
    assert "step_started" in collector.types()
