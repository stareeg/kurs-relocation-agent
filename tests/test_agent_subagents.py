"""A-8 субагенты шага (OQ-28): вызов как `task`, лимит на шаг, события, бюджет.

Живых моделей нет: исполнитель и субагенты — `ScriptedChatModel` с заготовленными
ходами; инструменты субагентов ходят в демо-данные `FakeDemoDb` (и LLM-порт подменён
для скоринга/условий). Проверяем: исполнитель видит `task` рядом с доменными
инструментами; субагент делает вызовы и возвращает structured-вывод по схеме; третий
вызов `task` на шаг отклоняется как данные; события субагентов уходят в поток с тегом
`subagent`; вакансии субагента сливаются в состояние шага; бюджет считает вызовы
модели субагентов.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from core.app.agent.contracts import ToolContext
from core.app.agent.events import AgentEvent
from core.app.agent.graph import AgentDeps, run_agent_goal
from core.app.agent.harness import build_step_agent
from core.app.agent.llm import (
    AGENT_SUB_COUNTRY,
    AGENT_SUB_VACANCY,
    ensure_agent_features_registered,
)
from core.app.agent.state import RunLimits
from core.app.agent.subagents import (
    COUNTRY_RESEARCHER,
    VACANCY_ASSESSOR,
    SubagentGate,
    build_subagent_specs,
)
from core.app.agent.tools import TOOLS, StepRecorder, ensure_tools_registered, to_langchain_tools
from core.domains.opportunities.models import TermEvidence, VacancyWorkTerms
from core.platform.llm.registry import require_feature
from tests.fakes import FakeDemoDb, FakeLlm, ScriptedChatModel, use_fake_llm

ensure_tools_registered()
ensure_agent_features_registered()

GOAL = "Оцени вакансии backend и проверь условия въезда"


@pytest.fixture(autouse=True)
def _resume_cache_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Кэш резюме в `structured_store` — глобальный LRU; тесты не делят записи."""
    monkeypatch.setattr("core.domains.profile.structured_store._cache", OrderedDict())


class Collector:
    """Тестовый наблюдатель: копит события в порядке прихода."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: str) -> list[AgentEvent]:
        return [e for e in self.events if e.type == event_type]


def _plan_spec(*steps: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "steps": [
            {"id": sid, "title": title, "done_criteria": criteria} for sid, title, criteria in steps
        ],
        "note": "цель понята",
    }


def _replan_spec(action: str) -> dict[str, Any]:
    return {"action": action, "reason": "решение по наблюдениям", "steps": []}


def _task_call(call_id: str = "c1", role: str = VACANCY_ASSESSOR) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "task",
                "args": {"description": "оцени вакансии", "subagent_type": role},
                "id": call_id,
            }
        ],
    )


def _verdict_tool_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "VacancyAssessmentResult",
                "args": {
                    "verdicts": [
                        {
                            "vacancy_id": "demo-102",
                            "title": "Applied AI Engineer",
                            "score": 84,
                            "recommendation": "apply: ловушка ВНЖ ЕС",
                            "traps": [
                                {
                                    "statement": "нужен ВНЖ ЕС",
                                    "quote": "нужен ВНЖ ЕС",
                                    "vacancy_id": "demo-102",
                                }
                            ],
                        }
                    ],
                    "gaps": [],
                    "answer": "demo-102 подходит, ловушка — ВНЖ ЕС",
                },
                "id": "s2",
            }
        ],
    )


def _deps(
    collector: Collector | None = None,
    *,
    executor: ScriptedChatModel | None = None,
    assessor: ScriptedChatModel | None = None,
    researcher: ScriptedChatModel | None = None,
    limits: RunLimits | None = None,
) -> AgentDeps:
    models: dict[str, Any] = {}
    if assessor is not None:
        models[VACANCY_ASSESSOR] = assessor
    if researcher is not None:
        models[COUNTRY_RESEARCHER] = researcher
    return AgentDeps(
        planner=ScriptedChatModel(
            responses=[
                AIMessage(
                    content=json.dumps(
                        _plan_spec(("s1", "Оценить вакансии", "вердикты с цитатами"))
                    )
                )
            ]
        ),
        executor=executor or ScriptedChatModel(responses=[AIMessage(content="готово")]),
        replanner=ScriptedChatModel(
            responses=[AIMessage(content=json.dumps(_replan_spec("finish")))]
        ),
        limits=limits or RunLimits(),
        tools=TOOLS,
        tool_context=ToolContext(account_id=1, db=FakeDemoDb()),
        observer=collector,
        subagent_models=models,
    )


# ------------------------------------------------------------------- каталог и лимит


def test_subagent_roles_declared_with_low_features():
    """Обе роли объявлены в реестре LLM-фич на basic/low (OQ-28)."""
    for name in (AGENT_SUB_COUNTRY, AGENT_SUB_VACANCY):
        feature = require_feature(name)
        assert feature.tier == "basic"
        assert feature.reasoning_effort == "low"


def test_build_specs_two_roles_with_own_tools():
    """Спеки: две роли, свои наборы инструментов, свой structured-возврат."""
    recorder = StepRecorder("s1", 1)
    specs, gate = build_subagent_specs(
        {
            COUNTRY_RESEARCHER: ScriptedChatModel(responses=[]),
            VACANCY_ASSESSOR: ScriptedChatModel(responses=[]),
        },
        ToolContext(account_id=1, db=FakeDemoDb()),
        recorder,
        RunLimits(),
        None,
    )
    assert isinstance(gate, SubagentGate)
    by_name = {spec["name"]: spec for spec in specs}
    assert set(by_name) == {COUNTRY_RESEARCHER, VACANCY_ASSESSOR}
    assessor_tools = [t.name for t in by_name[VACANCY_ASSESSOR]["tools"]]
    researcher_tools = [t.name for t in by_name[COUNTRY_RESEARCHER]["tools"]]
    assert "score_vacancy" in assessor_tools and "read_work_terms" in assessor_tools
    assert "score_vacancy" not in researcher_tools
    assert "read_work_terms" in researcher_tools
    assert "queue_application" not in assessor_tools + researcher_tools, (
        "действие остаётся только у основного агента"
    )


async def test_executor_sees_task_tool_alongside_domain_tools():
    """С субагентами исполнитель видит доменные инструменты плюс `task` (OQ-28)."""
    executor = ScriptedChatModel(responses=[AIMessage(content="готово")])
    recorder = StepRecorder("s1", 1)
    specs, gate = build_subagent_specs(
        {VACANCY_ASSESSOR: ScriptedChatModel(responses=[])},
        ToolContext(account_id=1, db=FakeDemoDb()),
        recorder,
        RunLimits(),
        None,
    )
    agent = build_step_agent(
        model=executor,
        tools=to_langchain_tools(TOOLS, ToolContext(account_id=1, db=FakeDemoDb()), recorder),
        system_prompt="тест",
        subagents=specs,
        middleware=[gate],
    )
    await agent.ainvoke({"messages": [("user", "тест")]})
    assert executor.seen_tools, "модель хотя бы раз вызвана"
    expected = sorted([*(t.name for t in TOOLS), "task"])
    for names in executor.seen_tools:
        assert sorted(names) == expected, f"инструменты шага: {names}, ожидались {expected}"


# ------------------------------------------------------------------- живой вызов task


async def test_task_call_runs_subagent_and_returns_structured(monkeypatch):
    """Субагент делает вызовы инструментов и возвращает structured-вывод по схеме."""

    def on_structured(feature: str, schema: type | None = None, **_kw: Any) -> Any:
        if feature == "vacancy_work_terms":
            return VacancyWorkTerms(
                engagement="b2b",
                geo_scope="region",
                residency_required=True,
                currency="EUR",
                rate_period="year",
                rate_min=90_000,
                rate_max=110_000,
                overlap_hours_required=4,
                evidence=[TermEvidence(field="residency_required", quote="нужен ВНЖ ЕС")],
            )
        raise AssertionError(f"неожиданная фича: {feature}")

    use_fake_llm(monkeypatch, FakeLlm(on_structured=on_structured))
    collector = Collector()
    executor = ScriptedChatModel(
        responses=[
            _task_call(),
            AIMessage(content="Оценка готова: demo-102 подходит, ловушка — ВНЖ ЕС."),
        ]
    )
    assessor = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "read_work_terms", "args": {"vacancy_id": "demo-102"}, "id": "s1"}
                ],
            ),
            _verdict_tool_call(),
        ]
    )
    state = await run_agent_goal(GOAL, deps=_deps(collector, executor=executor, assessor=assessor))

    assert state["stop_reason"] == "answered"
    assert "task" in (state["observations"][0].tools), "вызов task в инструментах шага"
    assert any("task(vacancy_assessor)" in s for s in state["observations"][0].summaries)
    tagged = [
        e for e in collector.of_type("tool_called") if e.payload.get("subagent") == VACANCY_ASSESSOR
    ]
    assert any(e.payload["tool"] == "read_work_terms" for e in tagged), (
        "вызовы инструментов субагента видны в потоке с тегом роли"
    )
    task_events = [e for e in collector.of_type("tool_called") if e.payload["tool"] == "task"]
    assert task_events and task_events[0].payload["ok"] is True


async def test_task_limit_rejects_third_call_with_data(monkeypatch):
    """Лимит OQ-28: третий вызов `task` на шаг отклоняется сообщением-данными."""
    collector = Collector()
    assessor = ScriptedChatModel(responses=[AIMessage(content="не вызывался")])
    executor = ScriptedChatModel(
        responses=[
            _task_call("c1"),
            _task_call("c2"),
            _task_call("c3"),
            AIMessage(content="продолжаю своими инструментами"),
        ]
    )
    state = await run_agent_goal(
        GOAL,
        deps=_deps(
            collector,
            executor=executor,
            assessor=assessor,
            limits=RunLimits(max_subagent_calls=2),
        ),
    )

    assert state["stop_reason"] == "answered"
    task_events = [e for e in collector.of_type("tool_called") if e.payload["tool"] == "task"]
    assert [e.payload["ok"] for e in task_events] == [True, True, False], (
        f"третий вызов отклонён: {[e.payload for e in task_events]}"
    )
    assert "лимит" in str(task_events[2].payload["error"])
    assert state["model_calls"] >= 6, "бюджет считает и вызовы субагентов"


async def test_researcher_vacancies_merge_into_step_state():
    """Вакансии, найденные субагентом, попадают в состояние запуска (через gate)."""
    collector = Collector()
    executor = ScriptedChatModel(
        responses=[
            _task_call("c1", role=COUNTRY_RESEARCHER),
            AIMessage(content="Собрал факты по стране."),
        ]
    )
    researcher = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "search_vacancies", "args": {"query": "kestrel"}, "id": "s1"}],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "CountryResearchResult",
                        "args": {
                            "country": "Германия",
                            "findings": [
                                {
                                    "topic": "резидентство",
                                    "statement": "нужен ВНЖ ЕС",
                                    "quote": "нужен ВНЖ ЕС",
                                    "vacancy_id": "demo-102",
                                }
                            ],
                            "gaps": ["налоги не проверены"],
                            "answer": "для demo-102 нужен ВНЖ ЕС",
                        },
                        "id": "s2",
                    }
                ],
            ),
        ]
    )
    state = await run_agent_goal(
        GOAL, deps=_deps(collector, executor=executor, researcher=researcher)
    )

    assert state["stop_reason"] == "answered"
    assert any(v["id"].startswith("demo-") for v in state["vacancies"]), (
        f"вакансии субагента в состоянии: {state['vacancies']}"
    )
    researcher_events = [
        e
        for e in collector.of_type("tool_called")
        if e.payload.get("subagent") == COUNTRY_RESEARCHER
    ]
    assert any(e.payload["tool"] == "search_vacancies" for e in researcher_events)
