"""A-5 самопроверка шага и судья итога: цитаты кодом, смысл — моделью, сбой — не падение.

Живых моделей нет: судьи — `ScriptedChatModel` с JSON `{reason, verdict}` в ответе,
граф крутится на демо-данных `FakeDemoDb`, как в test_agent_graph. Проверяем: судья
шага дополняет код-эвристику чека, судья итога проверяет цитаты кодом подстрокой
(приём work_terms) и смысл моделью, провал отправляет агента на доработку (петля
ограничена `max_judge_reworks`), сбой судьи — честное «не проверяется».
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from core.app.agent.contracts import ToolContext
from core.app.agent.events import AgentEvent
from core.app.agent.graph import AgentDeps, build_agent_graph, run_agent_goal
from core.app.agent.judge import (
    JudgeSpec,
    extract_quotes,
    final_answer_text,
    has_findings,
    judge_node,
    quote_check,
    quote_failures_of,
)
from core.app.agent.state import AgentState, Observation, PlanStep, RunLimits
from core.app.agent.tools import TOOLS, ensure_tools_registered
from tests.fakes import FakeDemoDb, ScriptedChatModel

ensure_tools_registered()

GOAL = "Найди вакансию backend с международной оплатой и назови лучшую"

ANSWER_WITH_QUOTE = "Лучший вариант — «Applied AI Engineer» в Kestrel Analytics."
ANSWER_WITHOUT_QUOTE = "Лучший вариант — Applied AI Engineer в Kestrel Analytics."


def _judge_json(verdict: str, reason: str = "решение по смыслу") -> AIMessage:
    return AIMessage(content=json.dumps({"reason": reason, "verdict": verdict}))


def _plan_spec(*steps: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "steps": [
            {"id": sid, "title": title, "done_criteria": criteria}
            for sid, title, criteria in steps
        ],
        "note": "цель понята",
    }


class CapturingChatModel(ScriptedChatModel):
    """Фейк с записью входных сообщений: проверяем, что увидели судья и планировщик."""

    seen_prompts: list[list[str]] = []

    def _generate(
        self, messages: list, stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ):
        self.seen_prompts = self.seen_prompts + [str(m.content) for m in messages]
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class ExplodingChatModel(ScriptedChatModel):
    """Судья, который падает: сбой судьи — не падение запуска (A-5)."""

    def _generate(
        self, messages: list, stop: list[str] | None = None, run_manager: Any = None, **kwargs: Any
    ):
        raise RuntimeError("судья недоступен")


class EventCollector:
    """Тестовый наблюдатель: копит события в порядке прихода."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    def of_type(self, event_type: str) -> list[AgentEvent]:
        return [e for e in self.events if e.type == event_type]


def _deps(
    planner: ScriptedChatModel,
    executor: ScriptedChatModel,
    replanner: ScriptedChatModel,
    *,
    judge_step: ScriptedChatModel | None = None,
    judge_final: ScriptedChatModel | None = None,
    limits: RunLimits | None = None,
    observer: EventCollector | None = None,
) -> AgentDeps:
    return AgentDeps(
        planner=planner,
        executor=executor,
        replanner=replanner,
        limits=limits or RunLimits(),
        tools=TOOLS,
        tool_context=ToolContext(account_id=1, db=FakeDemoDb()),
        observer=observer,
        judge_step=judge_step,
        judge_final=judge_final,
    )


def _state(**overrides: Any) -> AgentState:
    plan = overrides.pop(
        "plan", [PlanStep(id="s1", title="Найти вакансии", done_criteria="список вакансий")]
    )
    state: AgentState = {
        "goal": GOAL,
        "note": "",
        "plan": plan,
        "plan_changes": [],
        "replan_reason": None,
        "current_step_id": None,
        "replan_action": None,
        "step_verdict": None,
        "judge_verdict": None,
        "reworks_used": 0,
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


def _executor(responses: list[AIMessage]) -> ScriptedChatModel:
    return ScriptedChatModel(responses=responses)


def _search_then(answer: AIMessage) -> ScriptedChatModel:
    """Исполнитель: поиск вакансий (источник цитат) и текстовый ответ."""
    return _executor(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_vacancies", "args": {"query": "kestrel"}, "id": "c1"}
                ],
            ),
            answer,
        ]
    )


def _graph_inputs():
    planner = ScriptedChatModel(
        responses=[
            AIMessage(content=json.dumps(_plan_spec(("s1", "Найти вакансии", "список вакансий"))))
        ]
    )
    replanner = ScriptedChatModel(
        responses=[
            AIMessage(
                content=json.dumps({"action": "finish", "reason": "вариант назван", "steps": []})
            )
        ]
    )
    return planner, replanner


# ------------------------------------------------------------------- цитаты кодом


def test_extract_quotes_and_failures():
    """Код-проверка цитат: «…» и парные "…", минимум 8 знаков, проверка подстрокой."""
    text = "Ловушка «нужен ВНЖ ЕС» и требование \"Right to work in the EU\" в тексте."
    quotes = extract_quotes(text)
    assert quotes == ["нужен ВНЖ ЕС", "Right to work in the EU"]

    evidence = ["Условия: нужен ВНЖ ЕС или право работать в ЕС."]
    assert quote_failures_of(quotes, evidence) == ["Right to work in the EU"]
    assert quote_failures_of([], evidence) == []
    assert quote_failures_of(["короткая"], evidence) == ["короткая"], "меньше 8 знаков не цитата"


def test_quote_check_missing_quote():
    """Вывод без единой цитаты при живых данных — провал уровня 2 (критерий 4.1)."""
    obs = Observation(step_id="s1", index=1, tools=["search_vacancies"], summaries=["поиск: 1"])
    state = _state(observations=[obs])
    assert has_findings(state) is True
    failures, quotes, missing = quote_check(state)
    assert missing is True and quotes == [] and failures == []

    quiet = _state()
    assert has_findings(quiet) is False, "без данных цитата не требуется"


def test_final_answer_text_prefers_model_answer():
    """Судья смотрит на ответ модели шага, без ответа — на сводки."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer=ANSWER_WITH_QUOTE,
    )
    assert final_answer_text(_state(observations=[obs])) == ANSWER_WITH_QUOTE
    assert (
        final_answer_text(_state(observations=[obs.model_copy(update={"answer": None})]))
        == "поиск: найдена Applied AI Engineer"
    )


def test_evidence_excludes_agent_answers():
    """Материалы — только результаты инструментов: цитата не сходится с самим собой."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer="Вывод: «какая-то цитата из головы».",
    )
    failures, quotes, missing = quote_check(_state(observations=[obs]))
    assert quotes == ["какая-то цитата из головы"]
    assert failures == ["какая-то цитата из головы"], "выдуманная цитата не проходит"
    assert missing is False


# ------------------------------------------------------------------- узел судьи итога


async def test_judge_node_fabricated_quote_fails_without_model():
    """Провал цитат детерминирован: выдуманная цитата ловится кодом даже без судьи."""
    answer = "Лучший вариант — «Выдуманная цитата из головы»."
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer=answer,
    )
    out = await judge_node(None, RunLimits())(_state(observations=[obs]), None)
    verdict = out["judge_verdict"]
    assert verdict["verdict"] == "fail"
    assert verdict["level"] == "final"
    assert verdict["quote_failures"] == ["Выдуманная цитата из головы"]
    assert out["reworks_used"] == 1, "первый провал отправляет на доработку"
    assert "stop_reason" not in out, "предел доработок ещё не исчерпан"


async def test_judge_node_missing_quote_is_meaning_for_model():
    """Отсутствие цитат — не приговор кода: судья видит данные и решает по смыслу."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer=ANSWER_WITHOUT_QUOTE,
    )
    # Без судьи: unverified — прежнее поведение, финал без судебного замечания.
    out = await judge_node(None, RunLimits())(_state(observations=[obs]), None)
    assert out["judge_verdict"]["verdict"] == "unverified"
    assert "reworks_used" in out and out["reworks_used"] == 0

    # Судья говорит «вывод не опирается на материалы» — провал.
    judge = ScriptedChatModel(responses=[_judge_json("fail", "вывод без опоры-цитаты")])
    out = await judge_node(judge, RunLimits())(_state(observations=[obs]), None)
    assert out["judge_verdict"]["verdict"] == "fail"
    assert out["reworks_used"] == 1


async def test_judge_node_stop_after_reworks_exhausted():
    """Доработки исчерпаны: честный финал judge_failed с причиной судьи."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer=ANSWER_WITHOUT_QUOTE,
    )
    limits = RunLimits(max_judge_reworks=2)
    judge = ScriptedChatModel(responses=[_judge_json("fail", "вывод без опоры-цитаты")])
    out = await judge_node(judge, limits)(_state(observations=[obs], reworks_used=2), None)
    assert out["stop_reason"] == "judge_failed"
    assert out["judge_verdict"]["verdict"] == "fail"
    assert out["note"], "причина вердикта уходит в честный финал"


async def test_judge_node_model_meaning_pass_and_fail():
    """Код чист, смысл судит модель: pass пропускает, fail отправляет на доработку."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer=ANSWER_WITH_QUOTE,
    )
    judge = ScriptedChatModel(responses=[_judge_json("pass", "цель покрыта")])
    out = await judge_node(judge, RunLimits())(_state(observations=[obs]), None)
    assert out["judge_verdict"]["verdict"] == "pass"
    assert out["judge_verdict"]["reason"] == "цель покрыта"
    assert out["reworks_used"] == 0

    judge_fail = ScriptedChatModel(responses=[_judge_json("fail", "цель не покрыта")])
    out = await judge_node(judge_fail, RunLimits())(_state(observations=[obs]), None)
    assert out["judge_verdict"]["verdict"] == "fail"
    assert out["judge_verdict"]["reason"] == "цель не покрыта"
    assert out["reworks_used"] == 1


async def test_judge_node_crash_is_unverified():
    """Сбой судьи — не падение: unverified как данные, код-проверка чиста — финал идёт."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["search_vacancies"],
        summaries=["поиск: найдена Applied AI Engineer"],
        answer=ANSWER_WITH_QUOTE,
    )
    out = await judge_node(ExplodingChatModel(responses=[]), RunLimits())(
        _state(observations=[obs]), None
    )
    assert out["judge_verdict"]["verdict"] == "unverified"
    assert "судья недоступен" in out["judge_verdict"]["reason"]
    assert out["reworks_used"] == 0 and "stop_reason" not in out


async def test_judge_node_schema():
    """Схема судьи строгая: оба поля обязательны, вердикт только pass/fail."""
    spec = JudgeSpec.model_validate({"reason": "ок", "verdict": "pass"})
    assert spec.verdict == "pass"
    try:
        JudgeSpec.model_validate({"reason": "ок", "verdict": "не знаю"})
    except Exception:  # noqa: BLE001 — вне схемы вердикт отвергается
        pass
    else:  # pragma: no cover — проваливаем, если схема пропустила чужое значение
        raise AssertionError("JudgeSpec принял вердикт вне pass/fail")


# ------------------------------------------------------------------- судья шага (уровень 1)


async def test_step_judge_pass_and_fail_in_check():
    """Уровень 1: pass закрывает шаг, fail держит шаг открытым и растит неудачи."""
    from core.app.agent.graph import check_node

    plan = [PlanStep(id="s1", title="Найти вакансии", done_criteria="список вакансий")]
    obs = Observation(
        step_id="s1", index=1, tools=["search_vacancies"], summaries=["поиск: найдена Applied AI Engineer"], answer="нашёл"
    )

    judge_pass = ScriptedChatModel(responses=[_judge_json("pass", "результат отвечает шагу")])
    out = await check_node(judge_pass)(_state(plan=plan, observations=[obs]), None)
    assert out["plan"][0].status == "done"
    assert out["step_verdict"]["verdict"] == "pass" and out["failure_streak"] == 0

    judge_fail = ScriptedChatModel(responses=[_judge_json("fail", "шаг не сделан")])
    out = await check_node(judge_fail)(_state(plan=plan, observations=[obs]), None)
    assert "plan" not in out, "шаг не закрывается вердиктом fail"
    assert out["failure_streak"] == 1
    assert out["step_verdict"]["verdict"] == "fail"


async def test_step_judge_crash_keeps_old_behavior():
    """Сбой судьи шага: прежнее поведение (без ошибки — шаг закрыт), вердикт unverified."""
    from core.app.agent.graph import check_node

    plan = [PlanStep(id="s1", title="Найти вакансии", done_criteria="список вакансий")]
    obs = Observation(step_id="s1", index=1, tools=["search_vacancies"], summaries=["поиск: ок"])
    out = await check_node(ExplodingChatModel(responses=[]))(
        _state(plan=plan, observations=[obs]), None
    )
    assert out["plan"][0].status == "done"
    assert out["step_verdict"]["verdict"] == "unverified"
    assert out["failure_streak"] == 0


# ------------------------------------------------------------------- полный прогон


async def test_final_judge_rework_then_pass():
    """Провал итога → доработка через планировщика → второй вердикт pass → answered."""
    planner, replanner = _graph_inputs()
    executor = _search_then(AIMessage(content=ANSWER_WITH_QUOTE))
    judge_step = ScriptedChatModel(responses=[_judge_json("pass", "результат отвечает шагу")])
    judge_final = ScriptedChatModel(
        responses=[
            _judge_json("fail", "вывод без опоры-цитаты"),
            _judge_json("pass", "цель покрыта, цитата сходится"),
        ]
    )
    collector = EventCollector()
    state = await run_agent_goal(
        GOAL,
        deps=_deps(
            planner,
            executor,
            replanner,
            judge_step=judge_step,
            judge_final=judge_final,
            observer=collector,
        ),
    )

    assert state["stop_reason"] == "answered"
    assert state["reworks_used"] == 1, "один провал итога — одна доработка"
    assert state["judge_verdict"]["verdict"] == "pass"

    final_verdicts = [
        e for e in collector.of_type("judge_verdict") if e.payload.get("level") == "final"
    ]
    assert [e.payload["verdict"] for e in final_verdicts] == ["fail", "pass"]
    assert final_verdicts[0].payload["quote_failures"] == [], "провал по смыслу, цитаты сходятся"
    step_verdicts = [
        e for e in collector.of_type("judge_verdict") if e.payload.get("level") == "step"
    ]
    assert step_verdicts and all(e.payload["verdict"] == "pass" for e in step_verdicts)
    assert any(e.payload["step_id"] == "s1" for e in step_verdicts)


async def test_final_judge_fail_exhausts_reworks():
    """Устойчивый провал итога: две доработки, затем честный финал judge_failed."""
    planner, replanner = _graph_inputs()
    executor = _search_then(AIMessage(content=ANSWER_WITHOUT_QUOTE))
    judge_step = ScriptedChatModel(responses=[_judge_json("pass", "результат отвечает шагу")])
    judge_final = ScriptedChatModel(
        responses=[_judge_json("fail", "вывод без опоры-цитаты")]
    )
    state = await run_agent_goal(
        GOAL,
        deps=_deps(
            planner,
            executor,
            replanner,
            judge_step=judge_step,
            judge_final=judge_final,
            limits=RunLimits(max_judge_reworks=2),
        ),
    )

    assert state["stop_reason"] == "judge_failed"
    assert state["reworks_used"] == 2, "ровно столько доработок, сколько разрешено"
    assert state["judge_verdict"]["verdict"] == "fail"
    answer = str(state["answer"])
    assert "Не удалось закончить цель" in answer
    assert "Причина судьи" in answer, "честный финал называет причину вердикта"


async def test_final_judge_crash_continues_honestly():
    """Сбой судьи итога: unverified, запуск завершается как раньше (answered)."""
    planner, replanner = _graph_inputs()
    executor = _search_then(AIMessage(content=ANSWER_WITH_QUOTE))
    state = await run_agent_goal(
        GOAL,
        deps=_deps(planner, executor, replanner, judge_final=ExplodingChatModel(responses=[])),
    )
    assert state["stop_reason"] == "answered"
    assert state["judge_verdict"]["verdict"] == "unverified"
    assert "судья недоступен" in str(state["judge_verdict"]["reason"])
    assert state["reworks_used"] == 0


async def test_planner_receives_judge_remark():
    """Замечание судьи попадает во вход планировщика на доработке (A-5)."""
    planner = CapturingChatModel(
        responses=[
            AIMessage(content=json.dumps(_plan_spec(("s1", "Найти вакансии", "список вакансий"))))
        ]
    )
    replanner = ScriptedChatModel(
        responses=[
            AIMessage(
                content=json.dumps({"action": "finish", "reason": "вариант назван", "steps": []})
            )
        ]
    )
    # Второй прогон шага отвечает с цитатой — код-проверка чиста, модель-судья говорит pass.
    executor = _executor(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_vacancies", "args": {"query": "kestrel"}, "id": "c1"}
                ],
            ),
            AIMessage(content=ANSWER_WITHOUT_QUOTE),
            AIMessage(content=ANSWER_WITH_QUOTE),
        ]
    )
    judge_step = ScriptedChatModel(responses=[_judge_json("pass", "результат отвечает шагу")])
    judge_final = ScriptedChatModel(
        responses=[
            _judge_json("fail", "вывод без опоры-цитаты"),
            _judge_json("pass", "теперь с цитатой"),
        ]
    )
    state = await run_agent_goal(
        GOAL,
        deps=_deps(planner, executor, replanner, judge_step=judge_step, judge_final=judge_final),
    )
    assert state["stop_reason"] == "answered"
    assert state["reworks_used"] == 1
    judge_calls = [
        prompt
        for prompt in planner.seen_prompts
        if isinstance(prompt, str) and "Замечание судьи" in prompt
    ]
    assert len(judge_calls) >= 1, "планировщик увидел замечание судьи на доработке"
    assert any("вывод без опоры-цитаты" in call for call in judge_calls), "причина во входе"


async def test_graph_without_judges_keeps_old_semantics():
    """Без судей (None): цитаты кодом всё равно проверяются, смысл — «не проверяется»."""
    planner, replanner = _graph_inputs()
    executor = _search_then(AIMessage(content=ANSWER_WITH_QUOTE))
    collector = EventCollector()
    state = await run_agent_goal(
        GOAL, deps=_deps(planner, executor, replanner, observer=collector)
    )
    assert state["stop_reason"] == "answered"
    verdicts = collector.of_type("judge_verdict")
    assert verdicts, "событие judge_verdict отдаётся даже без судей"
    assert all(e.payload["verdict"] == "unverified" for e in verdicts)
    assert state["reworks_used"] == 0


async def test_fabricated_quote_fails_even_without_judge_model():
    """Выдуманная цитата ловится кодом и без модели-судьи: доработка, потом judge_failed."""
    planner, replanner = _graph_inputs()
    executor = _search_then(
        AIMessage(content="Лучший вариант — «Выдуманный ответ из головы».")
    )
    state = await run_agent_goal(GOAL, deps=_deps(planner, executor, replanner))
    assert state["stop_reason"] == "judge_failed", "код-проверка детерминирована без судьи"
    assert state["judge_verdict"]["verdict"] == "fail"
    assert state["reworks_used"] == 2


async def test_judge_state_survives_checkpoint():
    """Вердикты судьи — обычные поля состояния: переживают чекпойнтер."""
    from langgraph.checkpoint.memory import MemorySaver

    planner, replanner = _graph_inputs()
    executor = _search_then(AIMessage(content=ANSWER_WITH_QUOTE))
    judge_step = ScriptedChatModel(responses=[_judge_json("pass", "результат отвечает шагу")])
    judge_final = ScriptedChatModel(responses=[_judge_json("pass", "цель покрыта")])
    deps = _deps(
        planner, executor, replanner, judge_step=judge_step, judge_final=judge_final
    )
    graph = build_agent_graph(deps, checkpointer=MemorySaver())
    await graph.ainvoke({"goal": GOAL}, config={"configurable": {"thread_id": "t-judge"}})
    snapshot = await graph.aget_state({"configurable": {"thread_id": "t-judge"}})
    values = snapshot.values
    assert values["judge_verdict"]["verdict"] == "pass"
    assert values["step_verdict"]["verdict"] == "pass"
    assert values["reworks_used"] == 0
