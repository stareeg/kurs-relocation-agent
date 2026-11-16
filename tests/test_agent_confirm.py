"""A-3 подтверждение действия: interrupt/resume графа, «да» выполняет, «нет» отклоняет.

Живых моделей нет: планировщик/перестройка — `ScriptedChatModel` с JSON, исполнитель
вызывает `queue_application` на демо-данных. Чекпойнтер — MemorySaver; «перезапуск API»
в тесте — новый граф с тем же чекпойнтером: состояние резюмится (критерий A-3).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from core.app.agent.contracts import ToolContext
from core.app.agent.graph import AgentDeps, build_agent_graph, confirm_node
from core.app.agent.state import AgentState
from core.app.agent.tools import TOOLS, ensure_tools_registered
from tests.fakes import FakeDemoDb, ScriptedChatModel

ensure_tools_registered()

GOAL = "Поставь отклик на вакансию demo-101"
NOTE = "Здравствуйте! Готов обсудить позицию backend."


def _plan_spec(*steps: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "steps": [
            {"id": sid, "title": title, "done_criteria": criteria} for sid, title, criteria in steps
        ],
        "note": "цель понята: поставить отклик",
    }


def _replan_spec(action: str) -> dict[str, Any]:
    return {"action": action, "reason": "решение по наблюдениям", "steps": []}


def _executor() -> ScriptedChatModel:
    """Исполнитель: вызывает queue_application и заканчивает шаг текстом."""
    return ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "queue_application",
                        "args": {"vacancy_id": "demo-101", "cover_note": NOTE},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(content="Действие отложено до подтверждения человека."),
        ]
    )


def _deps(
    db: FakeDemoDb,
    *,
    planner_responses: list[AIMessage] | None = None,
    executor: ScriptedChatModel | None = None,
    replanner_responses: list[AIMessage] | None = None,
) -> AgentDeps:
    return AgentDeps(
        planner=ScriptedChatModel(
            responses=planner_responses
            or [
                AIMessage(
                    content=json.dumps(_plan_spec(("s1", "Поставить отклик", "отклик в очереди")))
                )
            ]
        ),
        executor=executor or _executor(),
        replanner=ScriptedChatModel(
            responses=replanner_responses or [AIMessage(content=json.dumps(_replan_spec("finish")))]
        ),
        tools=TOOLS,
        tool_context=ToolContext(account_id=1, db=db),
    )


_QUEUE_ARGS = {"vacancy_id": "demo-101", "cover_note": NOTE}


async def test_confirm_pauses_and_approval_executes_action():
    """Пауза на карточке → «да» → действие выполнено, шаг закрыт, запуск отвечает."""
    db = FakeDemoDb()
    saver = MemorySaver()
    config = {"configurable": {"thread_id": "t-approve"}}
    graph = build_agent_graph(_deps(db), checkpointer=saver)

    paused = await graph.ainvoke({"goal": GOAL}, config=config)
    interrupts = paused.get("__interrupt__") or ()
    assert interrupts, "граф встал на подтверждении"
    card = interrupts[0].value
    assert card["action"] == "queue_application"
    assert card["params"] == _QUEUE_ARGS
    snapshot = await graph.aget_state(config)
    assert snapshot.values["pending_action"]["action"] == "queue_application"
    assert db.executed == [], "без «да» человека ничего не пишется в базу"

    final = await graph.ainvoke(Command(resume={"approved": True}), config=config)
    assert final["stop_reason"] == "answered"
    assert final["pending_action"] is None
    writes = [sql for sql, _ in db.executed]
    assert any("update jobs" in sql for sql in writes), "текст письма ушёл в карточку"
    assert any("auto_apply_queue_overrides" in sql for sql in writes), "вакансия в очереди"
    assert final["plan"][0].status == "done"
    executed = [
        o for o in final["observations"] if "выполнено после подтверждения" in o.summaries[-1]
    ]
    assert executed, "наблюдение про выполнение действия записано"


async def test_pause_survives_graph_rebuild():
    """Рестарт API: новый граф с тем же чекпойнтером резюмит паузу и доводит до конца."""
    db = FakeDemoDb()
    saver = MemorySaver()
    config = {"configurable": {"thread_id": "t-restart"}}
    first = build_agent_graph(_deps(db), checkpointer=saver)
    paused = await first.ainvoke({"goal": GOAL}, config=config)
    assert paused.get("__interrupt__"), "пауза на подтверждении"

    # «Рестарт»: процесс умер, граф собирается заново с тем же чекпойнтером.
    second = build_agent_graph(_deps(db), checkpointer=saver)
    final = await second.ainvoke(Command(resume={"approved": True}), config=config)
    assert final["stop_reason"] == "answered"
    writes = [sql for sql, _ in db.executed]
    assert any("auto_apply_queue_overrides" in sql for sql in writes)
    assert final["pending_action"] is None


async def test_rejection_keeps_step_open():
    """«Нет»: наблюдение с ошибкой, шаг остаётся todo, агент продолжает без действия."""
    db = FakeDemoDb()
    saver = MemorySaver()
    config = {"configurable": {"thread_id": "t-reject"}}
    # Перестройка после повтора шага заканчивает запуск; после отклонения шаг
    # повторяется: исполнитель уже отработал скрипт, повтор отдаёт финальный текст.
    graph = build_agent_graph(
        _deps(db, replanner_responses=[AIMessage(content=json.dumps(_replan_spec("finish")))]),
        checkpointer=saver,
    )
    paused = await graph.ainvoke({"goal": GOAL}, config=config)
    assert paused.get("__interrupt__")

    final = await graph.ainvoke(Command(resume={"approved": False}), config=config)
    assert final["stop_reason"] == "answered"
    assert db.executed == [], "отклонённое действие не пишется в базу"
    rejected = [o for o in final["observations"] if o.error and "отклонил" in o.error]
    assert rejected, "наблюдение про отклонение записано"
    assert final["steps_taken"] == 2, "после отклонения шаг повторился (неудача ведёт к ретраю)"


def _tiny_graph(db: FakeDemoDb, observer: Any | None = None) -> Any:
    """Граф из одного узла confirm — прямой тест решения без полного цикла."""
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node(
        "confirm",
        confirm_node(ToolContext(account_id=1, db=db), observer, pausable=True),
    )
    graph.add_edge(START, "confirm")
    graph.add_edge("confirm", END)
    return graph.compile(checkpointer=MemorySaver())


async def test_confirm_node_rejection_observation_and_clear():
    """Отклонение в узле: наблюдение с ошибкой, карточка снята, база не тронута."""
    db = FakeDemoDb()
    graph = _tiny_graph(db)
    config = {"configurable": {"thread_id": "tiny-reject"}}
    state: dict[str, Any] = {
        "pending_action": {
            "action": "queue_application",
            "params": _QUEUE_ARGS,
            "step_id": "s1",
            "index": 1,
        }
    }
    paused = await graph.ainvoke(state, config=config)
    assert paused.get("__interrupt__")
    final = await graph.ainvoke(Command(resume={"approved": False}), config=config)
    assert final["pending_action"] is None
    observations = final["observations"]
    assert observations[-1].error and "отклонил" in observations[-1].error
    assert observations[-1].step_id == "s1"
    assert db.executed == []


@pytest.mark.parametrize("approved", [True, False])
async def test_confirm_node_approval_executes_tool(approved: bool):
    """«Да» в узле: execute_tool с автоподтверждением; тот же контекст — те же submissions."""
    db = FakeDemoDb()
    graph = _tiny_graph(db)
    config = {"configurable": {"thread_id": f"tiny-{approved}"}}
    state: dict[str, Any] = {
        "pending_action": {
            "action": "queue_application",
            "params": _QUEUE_ARGS,
            "step_id": "s1",
            "index": 1,
        }
    }
    await graph.ainvoke(state, config=config)
    final = await graph.ainvoke(Command(resume={"approved": approved}), config=config)
    observations = final["observations"]
    if approved:
        assert observations[-1].error is None
        assert any("auto_apply_queue_overrides" in sql for sql, _ in db.executed)
    else:
        assert observations[-1].error and "отклонил" in observations[-1].error
        assert db.executed == []
