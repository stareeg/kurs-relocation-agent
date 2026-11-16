"""Разбор прогонов демо на стенде 16.11: ошибки инструментов, судья итога, поиск.

Что ломало демо (запуски 16, 17, 20, 21): шаг, где модель сама исправила вызов, всё равно
проваливался; «нет такой вакансии» повторяло шаг впустую; после «да» итог судился по
JSON сводок и уходил на доработку с нуля, повторяя письмо и отклик; длинный запрос поиска
давал пусто, а подсказка звала в несуществующий «сбор вакансий».
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage

from core.app.agent.contracts import ToolCall, ToolContext
from core.app.agent.graph import _action_answer, check_node
from core.app.agent.judge import judge_node
from core.app.agent.state import AgentState, Observation, PlanStep, RunLimits
from core.app.agent.toolkit import execute_tool
from core.app.agent.tools import TOOL_BY_NAME, StepRecorder, ensure_tools_registered
from tests.fakes import FakeDemoDb, ScriptedChatModel

ensure_tools_registered()

GOAL = "Подбери лучшую вакансию, напиши письмо и поставь отклик"


def _state(**overrides: Any) -> AgentState:
    state: dict[str, Any] = {
        "goal": GOAL,
        "note": "",
        "plan": [PlanStep(id="s1", title="Выбрать вакансию", done_criteria="выбрана")],
        "observations": [],
        "vacancies": [],
        "reworks_used": 0,
        "steps_taken": 1,
        "model_calls": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        "failure_streak": 0,
    }
    state.update(overrides)
    return state  # type: ignore[return-value]


def _judge(verdict: str, reason: str) -> ScriptedChatModel:
    return ScriptedChatModel(
        responses=[AIMessage(content=json.dumps({"reason": reason, "verdict": verdict}))]
    )


# ------------------------------------------------------------------- ошибки в шаге


def test_successful_retry_of_same_tool_clears_step_error():
    """Модель ошиблась id, потом вызвала верно — шаг без ошибки (стенд, запуск 21)."""
    recorder = StepRecorder("s3", 3)
    score = TOOL_BY_NAME["score_vacancy"]
    recorder.record(score, {}, {"type": "not_found", "message": "вакансии x нет", "hint": ""})
    assert recorder.to_observation(None).error == "вакансии x нет"
    recorder.record(score, {"vacancy_id": "demo-101", "overall_score": 80}, None)
    obs = recorder.to_observation("готово")
    assert obs.error is None and obs.error_type is None
    assert any("ошибка — вакансии x нет" in s for s in obs.summaries), "история ошибки осталась"


def test_unresolved_error_keeps_its_type():
    recorder = StepRecorder("s1", 1)
    recorder.record(
        TOOL_BY_NAME["read_work_terms"],
        {},
        {"type": "not_found", "message": "вакансии no-such-job нет в собранной базе", "hint": ""},
    )
    recorder.record(TOOL_BY_NAME["search_vacancies"], {"items": [], "total": 0}, None)
    obs = recorder.to_observation("Такой вакансии нет в базе.")
    assert obs.error == "вакансии no-such-job нет в собранной базе"
    assert obs.error_type == "not_found"


async def test_model_side_error_with_answer_goes_to_judge():
    """«Нет такой вакансии» — тоже результат: шаг судит модель, а не провал без неё."""
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["read_work_terms"],
        summaries=["read_work_terms: ошибка — вакансии no-such-job нет в собранной базе"],
        error="вакансии no-such-job нет в собранной базе",
        error_type="not_found",
        answer="Вакансии no-such-job нет в базе — ищем похожую.",
    )
    judge = _judge("pass", "честно зафиксировано, что вакансии нет")
    out = await check_node(judge)(_state(observations=[obs]), {})
    assert out["step_verdict"]["verdict"] == "pass"
    assert out["failure_streak"] == 0
    assert out["plan"][0].status == "done"


async def test_service_failure_fails_without_judge():
    obs = Observation(
        step_id="s1",
        index=1,
        tools=["score_vacancy"],
        summaries=["score_vacancy: ошибка — модель недоступна"],
        error="модель недоступна",
        error_type="unavailable",
        answer="Не удалось оценить.",
    )
    judge = _judge("pass", "не должен вызываться")
    out = await check_node(judge)(_state(observations=[obs]), {})
    assert out["step_verdict"]["verdict"] == "fail"
    assert out["failure_streak"] == 1
    assert judge._cursor == 0, "судья не вызывался"


# ------------------------------------------------------------------- судья итога


async def test_no_rework_after_executed_action():
    """После «да» и выполненного отклика доработки нет: повтор мог бы откликнуться ещё раз."""
    plan = [PlanStep(id="s1", title="Поставить отклик", done_criteria="в очереди", status="done")]
    action = Observation(
        step_id="s1",
        index=1,
        tools=["queue_application"],
        summaries=["queue_application: выполнено после подтверждения человеком"],
        answer="Отклик на «Applied AI Engineer» в Kestrel Analytics поставлен в очередь.",
        action_done=True,
    )
    out = await judge_node(_judge("fail", "не обоснован выбор"), RunLimits())(
        _state(plan=plan, observations=[action]), {}
    )
    assert out["judge_verdict"]["verdict"] == "fail", "вердикт виден как данные"
    assert out["stop_reason"] == "answered"
    assert "plan" not in out, "шаг доработки не добавлен"


async def test_rework_appends_one_step_with_remark():
    plan = [PlanStep(id="s1", title="Найти вакансии", done_criteria="список", status="done")]
    obs = Observation(step_id="s1", index=1, tools=[], summaries=[], answer="Нашёл.")
    out = await judge_node(_judge("fail", "вывод без цитаты"), RunLimits())(
        _state(plan=plan, observations=[obs]), {}
    )
    assert [s.id for s in out["plan"]] == ["s1", "r1"]
    assert "вывод без цитаты" in out["plan"][1].done_criteria
    assert out["reworks_used"] == 1 and "stop_reason" not in out


def test_action_answer_names_vacancy_in_quotes():
    text = _action_answer(
        "queue_application",
        {"title": "AI Solutions Architect", "company": "Corvid Consulting"},
        "после подтверждения человеком",
    )
    assert text == (
        "Отклик на «AI Solutions Architect» в Corvid Consulting поставлен в очередь "
        "после подтверждения человеком."
    )


# ------------------------------------------------------------------- поиск


async def test_search_ranks_by_matched_words():
    """Длинный запрос модели больше не даёт пусто: хотя бы одно слово, первыми — где больше."""
    ctx = ToolContext(account_id=1, db=FakeDemoDb())
    result, error, _ = await execute_tool(
        ToolCall(
            id="c1", name="search_vacancies", arguments={"query": "kestrel несуществующееслово"}
        ),
        ctx,
    )
    assert error is None
    assert result["total"] >= 1
    assert result["items"][0]["company"] == "Kestrel Analytics"


async def test_search_hint_tells_empty_base_from_no_match():
    class EmptyDb(FakeDemoDb):
        async def fetch(self, sql: str, *args: Any) -> Any:
            return []

    result, _, _ = await execute_tool(
        ToolCall(id="c1", name="search_vacancies", arguments={}),
        ToolContext(account_id=1, db=EmptyDb()),
    )
    assert "сам агент сбор не запускает" in result["hint"]

    miss, _, _ = await execute_tool(
        ToolCall(id="c2", name="search_vacancies", arguments={"query": "zzzzqqq"}),
        ToolContext(account_id=1, db=FakeDemoDb()),
    )
    assert miss["total"] == 0
    assert "ослабьте фильтры" in miss["hint"] and "вакансий в базе: 7" in miss["hint"]


# ------------------------------------------------------------------- экран


def test_tool_brief_is_one_human_line():
    from core.app.agent.tools import tool_brief

    assert tool_brief("search_vacancies", {"items": [], "total": 0}) == "ничего не найдено"
    found = tool_brief(
        "search_vacancies",
        {"items": [{"title": "A"}, {"title": "B"}, {"title": "C"}, {"title": "D"}], "total": 6},
    )
    assert found == "найдено 6: A, B, C и ещё 3"
    assert tool_brief("score_vacancy", {"overall_score": 86, "recommendation": "strong_apply"}) == (
        "86 из 100, откликаться"
    )
    terms = tool_brief(
        "read_work_terms",
        {"engagement": "b2b", "geo_scope": "worldwide", "currency": "USD", "evidence": [{}, {}]},
    )
    assert terms == "B2B, из любой страны, USD; цитат: 2"
    assert tool_brief("queue_application", {"cancelled": True}) == "ждёт подтверждения человека"


def test_plan_diff_skips_status_only_changes():
    from core.app.agent.state import plan_diff

    before = [
        PlanStep(id="s1", title="Найти", done_criteria="c", status="done"),
        PlanStep(id="s2", title="Откликнуться", done_criteria="c"),
    ]
    after = [
        PlanStep(id="s1", title="Найти", done_criteria="c"),
        PlanStep(id="s2", title="Откликнуться", done_criteria="c", status="dropped"),
        PlanStep(id="s3", title="Найти похожую", done_criteria="c"),
    ]
    assert plan_diff(before, after)["changes"] == ["- s2: Откликнуться", "+ s3: Найти похожую"]


def test_step_gist_drops_prefix_and_tail():
    from core.app.agent.state import step_gist

    text = "Шаг s3 выполнен: лучшая вакансия — **AI Solutions Architect** (demo-108).\n- балл 86"
    assert step_gist(text) == "лучшая вакансия — AI Solutions Architect (demo-108)."
    long = "слово " * 80
    gist = step_gist(long)
    assert len(gist) <= 200 and gist.endswith("…")
