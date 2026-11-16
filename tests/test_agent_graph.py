"""A-1 каркас + A-2 инструменты поверх продукта: переходы графа, пределы, честный частичный итог.

Живых моделей нет: планировщик/перестройка — `ScriptedChatModel` с JSON в ответе,
исполнитель — тот же фейк с tool_calls (deepagents крутит свой цикл, инструменты
выполняются по контрактам из `core/app/agent` на демо-данных `FakeDemoDb`).
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from core.app.agent.contracts import ToolContext
from core.app.agent.graph import (
    AgentDeps,
    build_agent_graph,
    derive_stop_reason,
    route_after_check,
    route_after_plan,
    route_after_replan,
    route_after_step,
    run_agent_goal,
)
from core.app.agent.harness import build_step_agent
from core.app.agent.planner import PlanSpec, PlanStepSpec
from core.app.agent.replanner import PlanStepUpdate, ReplanSpec
from core.app.agent.state import (
    AgentState,
    Observation,
    PlanStep,
    RunLimits,
    apply_replan,
    first_todo_step,
    render_plan,
)
from core.app.agent.tools import (
    TOOLS,
    StepRecorder,
    build_run_context,
    ensure_tools_registered,
    to_langchain_tools,
)
from tests.fakes import FakeDemoDb, ScriptedChatModel

ensure_tools_registered()

GOAL = "Найди вакансию backend в Польше и скажи, какие условия въезда"


def _plan_spec(*steps: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "steps": [{"id": sid, "title": title, "done_criteria": criteria} for sid, title, criteria in steps],
        "note": "цель понята: подобрать вакансию и проверить правила",
    }


def _replan_spec(action: str, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"action": action, "reason": "решение по наблюдениям", "steps": steps or []}


def _deps(
    planner: ScriptedChatModel,
    executor: ScriptedChatModel,
    replanner: ScriptedChatModel,
    limits: RunLimits | None = None,
) -> AgentDeps:
    return AgentDeps(
        planner=planner,
        executor=executor,
        replanner=replanner,
        limits=limits or RunLimits(),
        tools=TOOLS,
        tool_context=ToolContext(account_id=1, db=FakeDemoDb()),
    )


def _state_with(plan: list[PlanStep], **overrides: Any) -> AgentState:
    state: AgentState = {
        "goal": GOAL,
        "note": "",
        "plan": plan,
        "plan_changes": [],
        "current_step_id": None,
        "replan_action": None,
        "observations": [],
        "vacancies": [],
        "routes": [],
        "pending_action": None,
        "steps_taken": 0,
        "replans_used": 0,
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "failure_streak": 0,
        "answer": None,
        "stop_reason": None,
        "error": None,
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# ------------------------------------------------------------------- счастливый путь


async def test_goal_passes_on_product_tools():
    """Цель проходит на инструментах продукта (демо-данные): план → шаг → finish → ответ."""
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
    replanner = ScriptedChatModel(responses=[AIMessage(content=json.dumps(_replan_spec("finish")))])

    state = await run_agent_goal(GOAL, deps=_deps(planner, executor, replanner))

    assert state["stop_reason"] == "answered"
    assert state["answer"] and "Kestrel" in str(state["answer"])
    assert state["steps_taken"] == 1
    assert state["plan"][0].status == "done"
    assert state["vacancies"], "вакансии из результата поиска попали в состояние"
    assert all(v["id"].startswith("demo-") for v in state["vacancies"]), "id из собранной базы"
    assert state["model_calls"] >= 3, "планировщик, шаг, перестройка посчитаны бюджетом"
    assert not state.get("error")


async def test_executor_sees_only_domain_tools():
    """deepagents показывает исполнителю только доменные инструменты (замер P0-4)."""
    executor = ScriptedChatModel(responses=[AIMessage(content="готово")])
    recorder = StepRecorder("s1", 1)
    agent = build_step_agent(
        model=executor,
        tools=to_langchain_tools(
            TOOLS, ToolContext(account_id=1, db=FakeDemoDb()), recorder
        ),
        system_prompt="тест",
    )
    await agent.ainvoke({"messages": [("user", "тест")]})
    assert executor.seen_tools, "модель хотя бы раз вызвана"
    for names in executor.seen_tools:
        assert sorted(names) == sorted(tool.name for tool in TOOLS), (
            f"инструменты исполнителя: {names}, ожидались только {sorted(t.name for t in TOOLS)}"
        )


# ------------------------------------------------------------------- проверка шага


async def test_check_marks_done_and_failure_streak():
    """Чек-эвристика: ошибка инструмента держит шаг todo и растит счётчик неудач."""
    from core.app.agent.graph import check_node

    plan = [PlanStep(id="s1", title="шаг", done_criteria="критерий")]
    ok = check_node()(_state_with(plan, observations=[Observation(step_id="s1", index=1, summaries=["ок"])]))
    assert ok["plan"][0].status == "done"
    assert ok["failure_streak"] == 0

    failed = check_node()(
        _state_with(plan, observations=[Observation(step_id="s1", index=1, error="таймаут")])
    )
    assert failed["failure_streak"] == 1


def test_routes_step_check_replan():
    """Переходы: план→шаг, шаг→подтверждение, пределы после чека, неудачи→перестройка."""
    limits = RunLimits(max_steps=2)
    plan = [PlanStep(id="s1", title="шаг", done_criteria="критерий")]
    # Предел шагов/бюджета проверяет ребро после чека (A-3: confirm стоит до чека).
    state_limit = _state_with(plan, steps_taken=2)
    assert route_after_step(state_limit) == "confirm"
    assert route_after_check(state_limit, limits) == "finalize", "предел шагов — честный финал"
    assert route_after_step(_state_with(plan, stop_reason="model_error")) == "finalize"
    assert route_after_plan(_state_with(plan, stop_reason="model_error")) == "finalize"

    state_ok = _state_with(
        plan,
        observations=[Observation(step_id="s1", index=1, summaries=["ок"])],
        steps_taken=1,
    )
    assert route_after_step(state_ok) == "confirm"
    state_checked = {**state_ok, "steps_taken": 1}
    assert route_after_check(state_checked, limits) == "replan"

    state_failed = _state_with(
        plan,
        observations=[Observation(step_id="s1", index=1, error="сбой")],
        steps_taken=1,
        failure_streak=1,
    )
    assert route_after_check(state_failed, limits) == "step", "одна неудача — повтор шага"
    state_stuck = {**state_failed, "failure_streak": limits.max_failure_streak + 1}
    assert route_after_check(state_stuck, limits) == "replan", "застряли — на перестройку"

    state_budget = _state_with(plan, steps_taken=1, model_calls=limits.max_model_calls)
    assert route_after_check(state_budget, limits) == "finalize", "бюджет — честный финал"

    state_rebuild = _state_with(plan, replan_action="rebuild", replans_used=1)
    assert route_after_replan(state_rebuild, limits) == "plan"
    state_finish = _state_with(plan, replan_action="finish")
    assert route_after_replan(state_finish, limits) == "finalize"
    state_continue = _state_with(plan, replan_action="continue")
    assert route_after_replan(state_continue, limits) == "step"


# ------------------------------------------------------------------- пределы


async def test_step_limit_gives_honest_partial():
    """Предел шагов: агент останавливается и честно отдаёт частичный результат."""
    planner = ScriptedChatModel(
        responses=[
            AIMessage(
                content=json.dumps(
                    _plan_spec(
                        ("s1", "Найти вакансии", "список"),
                        ("s2", "Проверить условия найма", "условия"),
                        ("s3", "Ещё шаг", "критерий"),
                    )
                )
            )
        ]
    )
    # Каждый шаг: вызов инструмента + текст; шаги только s1/s2 успеют при max_steps=2.
    executor = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "read_profile", "args": {}, "id": "c1"}]),
            AIMessage(content="Профиль получен."),
        ]
    )
    replanner = ScriptedChatModel(
        responses=[AIMessage(content=json.dumps(_replan_spec("continue", [
            {"id": "s1", "title": "Найти вакансии", "done_criteria": "список", "status": "done"},
            {"id": "s2", "title": "Проверить условия найма", "done_criteria": "условия", "status": "done"},
            {"id": "s3", "title": "Ещё шаг", "done_criteria": "критерий", "status": "todo"},
        ])))]
    )
    state = await run_agent_goal(GOAL, deps=_deps(planner, executor, replanner, RunLimits(max_steps=2)))

    assert state["stop_reason"] == "step_limit"
    assert state["steps_taken"] == 2
    assert state.get("plan_changes"), "перестройка продолжает — пишет «было/стало»"
    answer = str(state["answer"])
    assert "Не удалось закончить цель" in answer
    assert "Проверить условия найма" in answer, "закрытые шаги перечислены как «что удалось»"
    assert "Ещё шаг" in answer, "незакрытые шаги перечислены как «что осталось»"


async def test_model_budget_stops_run():
    """Бюджет вызовов: после исчерпания — остановка с частичным итогом (model_budget)."""
    planner = ScriptedChatModel(
        responses=[AIMessage(content=json.dumps(_plan_spec(("s1", "Найти вакансии", "список"))))]
    )
    executor = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "search_vacancies", "args": {}, "id": "c1"}]),
            AIMessage(content="Есть варианты."),
        ]
    )
    replanner = ScriptedChatModel(
        responses=[
            AIMessage(content=json.dumps(_replan_spec("continue", [
                {"id": "s1", "title": "Найти вакансии", "done_criteria": "список", "status": "todo"},
            ])))
        ]
    )
    state = await run_agent_goal(
        GOAL, deps=_deps(planner, executor, replanner, RunLimits(max_model_calls=3))
    )

    assert state["stop_reason"] == "model_budget"
    assert str(state["answer"]).startswith("Не удалось закончить цель")
    assert state["model_calls"] <= 4


# ------------------------------------------------------------------- перестройка


def test_apply_replan_by_id():
    """Правка по id: done не откатывается, отсутствующие шаги — dropped, новые — todo."""
    plan = [
        PlanStep(id="s1", title="поиск", done_criteria="список", status="done", result="есть"),
        PlanStep(id="s2", title="правила", done_criteria="правила"),
    ]
    updates = [
        {"id": "s1", "title": "поиск", "done_criteria": "список", "status": "todo"},
        {"id": "s2", "title": "условия найма Kestrel", "done_criteria": "правила", "status": "todo"},
        {"id": "s3", "title": "сравнить", "done_criteria": "таблица", "status": "todo"},
    ]
    after = apply_replan(plan, updates)
    assert [s.status for s in after if s.id == "s1"] == ["done"], "закрытый шаг не откатывается"
    assert [s.title for s in after if s.id == "s2"] == ["условия найма Kestrel"]
    assert [s.status for s in after if s.id == "s2"] == ["todo"]
    assert [s.id for s in after if s.id == "s3"] == ["s3"]


async def test_rebuild_goes_back_to_planner():
    """rebuild: перестройка отправляет план на пересборку, планировщик получает наблюдения."""
    planner = ScriptedChatModel(
        responses=[
            AIMessage(
                content=json.dumps(
                    _plan_spec(
                        ("s1", "Найти вакансии", "список"),
                        ("s2", "Откликнуться на demo-101", "отклик в очереди"),
                    )
                )
            ),
            AIMessage(
                content=json.dumps(
                    _plan_spec(
                        ("s1", "Найти вакансии", "список"),
                        ("s2", "Проверить условия найма", "условия"),
                    )
                )
            ),
        ]
    )
    # Шаг s2 (отклик) не подтверждён человеком → cancelled → чек считает это ошибкой? Нет:
    # cancelled — это не ошибка инструмента, а ожидание человека. Пусть шаг «упадёт»:
    # модель делает вызов queue_application, получает «cancelled», перестройка говорит rebuild.
    executor = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "queue_application", "args": {"vacancy_id": "demo-101", "cover_note": "Здравствуйте! Готов обсудить позицию backend."}, "id": "c1"}
                ],
            ),
            AIMessage(content="Действие ждёт подтверждения."),
        ]
    )
    replanner = ScriptedChatModel(
        responses=[
            AIMessage(content=json.dumps(_replan_spec("rebuild"))),
            AIMessage(content=json.dumps(_replan_spec("finish"))),
        ]
    )
    state = await run_agent_goal(GOAL, deps=_deps(planner, executor, replanner))

    assert state["replans_used"] >= 1
    assert state["plan"][1].title == "Проверить условия найма", "план пересобран"
    assert state["stop_reason"] == "answered"
    assert state.get("pending_action"), "карточка неподтверждённого действия в состоянии"


# ------------------------------------------------------------------- чекпойнты


async def test_memory_checkpointer_keeps_state():
    """Чекпойнтер в памяти: состояние запуска читается после завершения по thread_id."""
    planner = ScriptedChatModel(
        responses=[AIMessage(content=json.dumps(_plan_spec(("s1", "Найти вакансии", "список"))))]
    )
    executor = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "search_vacancies", "args": {}, "id": "c1"}]),
            AIMessage(content="Есть варианты."),
        ]
    )
    replanner = ScriptedChatModel(responses=[AIMessage(content=json.dumps(_replan_spec("finish")))])
    deps = _deps(planner, executor, replanner)
    graph = build_agent_graph(deps, checkpointer=MemorySaver())

    result = await graph.ainvoke(
        {"goal": GOAL}, config={"configurable": {"thread_id": "thread-a1"}}
    )
    snapshot = await graph.aget_state({"configurable": {"thread_id": "thread-a1"}})
    values = snapshot.values
    assert values["goal"] == GOAL
    assert values["stop_reason"] == result["stop_reason"]
    assert values["steps_taken"] == result["steps_taken"]
    assert first_todo_step(values["plan"]) is None


# ------------------------------------------------------------------- производные


def test_render_and_limits():
    """Мелочи состояния: рендер плана, потолок рекурсии шага, stop-reason по счётчикам."""
    plan = [
        PlanStep(id="s1", title="поиск", done_criteria="список", status="done", result="3 вакансии"),
        PlanStep(id="s2", title="правила", done_criteria="правила"),
    ]
    text = render_plan(plan)
    assert "[✓] s1" in text and "[—] s2" in text
    limits = RunLimits(step_max_turns=4)
    assert limits.step_recursion_limit == 12
    state = _state_with(plan, model_calls=limits.max_model_calls)
    assert derive_stop_reason(state, limits) == "model_budget"
    state_open = _state_with(plan, steps_taken=1)
    assert derive_stop_reason(state_open, limits) == "plan_exhausted", "план не закрыт — честный итог"
    state_finished = _state_with(plan, steps_taken=1, replan_action="finish")
    assert derive_stop_reason(state_finished, limits) == "answered"


def test_plan_spec_roundtrip():
    """Схемы планировщика/перестройки валидны и без лишних полей по умолчанию."""
    spec = PlanSpec.model_validate(
        {"steps": [{"id": "s1", "title": "поиск", "done_criteria": "список"}], "note": "цель"}
    )
    assert spec.steps[0].id == "s1"
    replan = ReplanSpec.model_validate(
        {
            "action": "continue",
            "reason": "ок",
            "steps": [{"id": "s1", "title": "поиск", "done_criteria": "список", "status": "done"}],
        }
    )
    assert replan.steps[0].status == "done"
