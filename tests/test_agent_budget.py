"""E-9: токены и цена запуска агента.

До E-9 бюджет слушал `on_chat_model_end`, которого у колбэков LangChain нет: ответ чат-модели
приходит в `on_llm_end`. Поэтому токены запуска были нулём на любом маршруте. Здесь —
настоящая `OpenRouterChatModel` на OpenAI-форме ответа (маршрут LiteLLM → GLM), граф с
судьёй (разбивка по группам), менеджер запусков (пределы, расход в событиях и строке
запуска, `agent_run_id` для сверки с `llm_usage`) и продолжение счёта с чекпойнта.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult, LLMResult
from langgraph.checkpoint.memory import MemorySaver

from core.app.agent.budget import RunBudget, feature_group, usage_of
from core.app.agent.contracts import ToolContext
from core.app.agent.graph import AgentDeps, run_agent_goal
from core.app.agent.llm import (
    AGENT_JUDGE_FINAL,
    AGENT_JUDGE_STEP,
    AGENT_PLAN,
    AGENT_REPLAN,
    AGENT_STEP,
)
from core.app.agent.runs import AgentRunsManager
from core.app.agent.state import RunLimits
from core.app.agent.tools import TOOLS, ensure_tools_registered
from core.platform.config.runtime import current_agent_run_id
from core.platform.llm.openrouter_chat import OpenRouterChatModel
from tests.fakes import FakeDemoDb, ScriptedChatModel
from tests.test_agent_runs import InMemoryRunsStore

ensure_tools_registered()

GOAL = "Найди вакансии backend с оплатой в валюте"


def _usage(message: AIMessage, tokens_in: int, tokens_out: int, cost: float) -> AIMessage:
    """Ответ двойника с usage так, как его кладёт `OpenRouterChatModel._to_chat_result`."""
    return message.model_copy(
        update={
            "usage_metadata": {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            },
            "response_metadata": {"model": "scripted", "cost_usd": cost},
        }
    )


class _AttributedModel(ScriptedChatModel):
    """Двойник, который запоминает, какому запуску приписан его вызов (`agent_run_id`)."""

    seen_run_ids: list[int | None] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.seen_run_ids.append(current_agent_run_id())
        return super()._generate(messages, stop, run_manager, **kwargs)


def _plan() -> str:
    return json.dumps(
        {
            "steps": [{"id": "s1", "title": "Найти вакансии", "done_criteria": "список вакансий"}],
            "note": "цель понята: найти вакансии",
        }
    )


def _models(seen: list[int | None] | None = None) -> dict[str, ScriptedChatModel]:
    planner_cls = _AttributedModel if seen is not None else ScriptedChatModel
    planner = planner_cls(
        responses=[_usage(AIMessage(content=_plan()), 300, 40, 0.001)],
        metadata={"agent": AGENT_PLAN},
    )
    if isinstance(planner, _AttributedModel) and seen is not None:
        planner.seen_run_ids = seen
    executor = ScriptedChatModel(
        responses=[
            _usage(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "search_vacancies", "args": {"query": "kestrel"}, "id": "c1"}
                    ],
                ),
                1000,
                20,
                0.002,
            ),
            _usage(AIMessage(content="Нашёл вакансию Applied AI Engineer."), 1200, 30, 0.003),
        ],
        metadata={"agent": AGENT_STEP},
    )
    replanner = ScriptedChatModel(
        responses=[
            _usage(
                AIMessage(
                    content=json.dumps({"action": "finish", "reason": "цель покрыта", "steps": []})
                ),
                400,
                25,
                0.0005,
            )
        ],
        metadata={"agent": AGENT_REPLAN},
    )
    verdict = json.dumps({"reason": "шаг выполнен", "verdict": "pass"})
    judge_step = ScriptedChatModel(
        responses=[_usage(AIMessage(content=verdict), 500, 15, 0.0007)],
        metadata={"agent": AGENT_JUDGE_STEP},
    )
    judge_final = ScriptedChatModel(
        responses=[
            _usage(
                AIMessage(content=json.dumps({"reason": "итог по цели", "verdict": "pass"})),
                700,
                35,
                0.0009,
            )
        ],
        metadata={"agent": AGENT_JUDGE_FINAL},
    )
    return {
        "planner": planner,
        "executor": executor,
        "replanner": replanner,
        "judge_step": judge_step,
        "judge_final": judge_final,
    }


def _deps(models: dict[str, ScriptedChatModel], account_id: int = 1) -> AgentDeps:
    return AgentDeps(
        planner=models["planner"],
        executor=models["executor"],
        replanner=models["replanner"],
        judge_step=models["judge_step"],
        judge_final=models["judge_final"],
        tools=TOOLS,
        tool_context=ToolContext(account_id=account_id, db=FakeDemoDb()),
    )


# ---------------------------------------------------------------- причина нулей


async def test_openrouter_model_on_litellm_route_reaches_budget(monkeypatch):
    """Настоящая модель продукта, OpenAI-форма ответа (LiteLLM → GLM): токены не ноль."""

    async def fake_run_with_retry(
        self: OpenRouterChatModel, payload: dict[str, Any], model: str
    ) -> tuple[dict[str, Any], int, float]:
        data = {
            "choices": [{"message": {"content": "ок"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 80, "total_tokens": 1280},
        }
        return data, 1, 0.0

    monkeypatch.setattr(OpenRouterChatModel, "_run_with_retry", fake_run_with_retry)
    model = OpenRouterChatModel(
        primary_model="glm-5.3-flash",
        base_url="http://litellm:4000/v1",
        api_key="sk-test",
        api_style="openai",
        agent=AGENT_STEP,
        metadata={"agent": AGENT_STEP},
    )
    budget = RunBudget(RunLimits(), self_hosted=frozenset({"glm-5.3-flash"}))

    await model.ainvoke([HumanMessage(content="привет")], config={"callbacks": [budget]})

    assert budget.calls == 1
    assert (budget.tokens_in, budget.tokens_out) == (1200, 80)
    assert budget.cost_usd > 0
    # GLM на своей ВМ: вся цена условная, по прайсу.
    assert budget.cost_self_hosted_usd == pytest.approx(budget.cost_usd)
    assert budget.by_group["agent"]["tokens_in"] == 1200


async def test_provider_cost_counts_as_real_spend(monkeypatch):
    """Цена OpenRouter из ответа (`usage.cost`) — реальные траты, не условная цена."""

    async def fake_run_with_retry(
        self: OpenRouterChatModel, payload: dict[str, Any], model: str
    ) -> tuple[dict[str, Any], int, float]:
        data = {
            "choices": [{"message": {"content": "pass"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 60, "cost": 0.00042},
        }
        return data, 1, 0.0

    monkeypatch.setattr(OpenRouterChatModel, "_run_with_retry", fake_run_with_retry)
    model = OpenRouterChatModel(
        primary_model="openrouter-reserve",
        base_url="http://litellm:4000/v1",
        api_key="sk-test",
        api_style="openai",
        agent=AGENT_JUDGE_STEP,
        metadata={"agent": AGENT_JUDGE_STEP},
    )
    budget = RunBudget(RunLimits(), self_hosted=frozenset({"glm-5.3-flash"}))

    await model.ainvoke([HumanMessage(content="проверь шаг")], config={"callbacks": [budget]})

    assert budget.cost_usd == pytest.approx(0.00042)
    assert budget.cost_self_hosted_usd == 0
    assert budget.by_group["judge"] == {
        "calls": 1,
        "tokens_in": 900,
        "tokens_out": 60,
        "cost_usd": pytest.approx(0.00042),
    }


def test_usage_falls_back_to_llm_output_token_usage():
    """Модель без `usage_metadata` (форма `ChatOpenAI`): токены из `llm_output.token_usage`."""
    result = LLMResult(
        generations=[[ChatGeneration(message=AIMessage(content="ок"))]],
        llm_output={
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 3},
            "model_name": "glm-5.3-flash",
        },
    )
    assert usage_of(result) == (10, 3, None, "glm-5.3-flash")


def test_feature_groups():
    assert feature_group(AGENT_PLAN) == "agent"
    assert feature_group(AGENT_STEP) == "agent"
    assert feature_group(AGENT_REPLAN) == "agent"
    assert feature_group("agent_sub_country") == "subagents"
    assert feature_group(AGENT_JUDGE_FINAL) == "judge"
    # LLM-фичи внутри инструментов: условия найма, письмо.
    assert feature_group("vacancy_work_terms") == "tools"
    assert feature_group("") == "tools"


# ---------------------------------------------------------------- граф


async def test_graph_run_sums_tokens_and_groups():
    """Запуск с судьёй: токены и цена складываются по всем вызовам, судья — своя группа."""
    state = await run_agent_goal(GOAL, deps=_deps(_models()))

    assert state["stop_reason"] == "answered"
    usage = state["usage"]
    # план 300+40, шаг 2 хода, перестройка, судья шага, судья итога
    assert state["tokens_in"] == 300 + 1000 + 1200 + 400 + 500 + 700
    assert state["tokens_out"] == 40 + 20 + 30 + 25 + 15 + 35
    assert usage["model_calls"] == state["model_calls"] == 6
    assert usage["cost_usd"] == pytest.approx(0.001 + 0.002 + 0.003 + 0.0005 + 0.0007 + 0.0009)
    assert usage["by_group"]["agent"]["calls"] == 4
    assert usage["by_group"]["judge"]["calls"] == 2
    assert usage["by_group"]["judge"]["tokens_in"] == 1200
    assert usage["by_group"]["subagents"]["calls"] == 0


def test_restore_continues_from_checkpoint():
    """Резюм после паузы: счёт продолжается с чекпойнта, цена и группы не теряются."""
    budget = RunBudget(RunLimits(), self_hosted=frozenset())
    budget.restore(
        {
            "model_calls": 5,
            "tokens_in": 4000,
            "tokens_out": 200,
            "usage": {
                "cost_usd": 0.0123,
                "cost_self_hosted_usd": 0.01,
                "by_group": {"judge": {"calls": 1, "tokens_in": 500, "tokens_out": 10}},
            },
        }
    )
    snap = budget.snapshot()
    assert (snap["model_calls"], snap["tokens_in"], snap["tokens_out"]) == (5, 4000, 200)
    assert snap["cost_usd"] == pytest.approx(0.0123)
    assert snap["cost_self_hosted_usd"] == pytest.approx(0.01)
    assert snap["by_group"]["judge"]["calls"] == 1
    assert snap["by_group"]["agent"]["calls"] == 0


# ---------------------------------------------------------------- менеджер запусков


async def test_manager_writes_usage_limits_and_attribution():
    """Пределы в `run_started`, снимки в `node_timing`, итог в `done` и в строке запуска."""
    seen: list[int | None] = []

    async def factory(account_id: int) -> AgentDeps:
        return _deps(_models(seen), account_id)

    store = InMemoryRunsStore()
    manager = AgentRunsManager(store, deps_factory=factory, checkpointer=MemorySaver())
    record = await manager.start_run(account_id=1, goal=GOAL)
    final = await manager.wait_settled(run_id=record.id, account_id=1, terminal=True)

    assert final is not None and final.status == "done"
    events = [e for e in store.events if e.run_id == record.id]
    started = next(e for e in events if e.type == "run_started")
    assert started.payload["limits"] == {"max_steps": 8, "max_model_calls": 40, "max_tokens": 200_000}

    timings = [e.payload["usage"] for e in events if e.type == "node_timing"]
    assert timings, "каждый узел несёт снимок расхода"
    calls = [u["model_calls"] for u in timings]
    assert calls == sorted(calls), "снимки монотонны"

    done = next(e for e in events if e.type == "done")
    assert done.payload["usage"]["tokens_in"] == 4100
    assert final.usage == done.payload["usage"]
    assert final.usage["by_group"]["judge"]["calls"] == 2
    # Вызовы модели приписаны запуску — так llm_usage.agent_run_id сходится со строкой.
    assert seen == [record.id]
    assert current_agent_run_id() is None
