"""Субагенты шага (A-8, OQ-28): исследователь страны и оценщик вакансий.

Вызываются исполнителем шага как инструмент `task` (deepagents subagents, режим
isolated): шаг сам решает, делегировать ли работу. Субагент делает 2–4 вызова своих
инструментов и возвращает структурированный вывод (Pydantic, все поля `required` —
правило GLM из замера P0-4). Оба тира — basic/low (решение OQ-13/OQ-28): локальная
задача и короткий промпт. Лимит — ≤ 2 вызова `task` на шаг (`RunLimits.
max_subagent_calls`): третий вызов получает ошибку как данные, шаг продолжается
своими инструментами. Вызовы модели субагента считает тот же `RunBudget` (колбэки
наследуются вниз по дереву запуска — deepagents передаёт родительский config), а
вызовы инструментов субагента уходят в поток запуска событиями `tool_called` с тегом
`subagent` (наблюдатель A-3) и сливают найденные вакансии в состояние шага.

Инструмент базы знаний (`search_country_facts`, K-1) добавится исследователю вместе
с модулем K-1; до тех пор его факты — условия найма вакансий страны с цитатами.
"""

from __future__ import annotations

import json
from typing import Any

from deepagents import SubAgent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from pydantic import BaseModel, Field

from core.app.agent.contracts import ToolContext
from core.app.agent.events import AgentEvent, RunObserver
from core.app.agent.prompts import load_prompt
from core.app.agent.state import RunLimits
from core.app.agent.tools import TOOL_BY_NAME, StepRecorder, to_langchain_tools

COUNTRY_RESEARCHER = "country_researcher"
"""Имя субагента-исследователя страны в каталоге инструмента `task`."""

VACANCY_ASSESSOR = "vacancy_assessor"
"""Имя субагента-оценщика вакансий в каталоге инструмента `task`."""

SUBAGENT_ROLES: tuple[str, ...] = (COUNTRY_RESEARCHER, VACANCY_ASSESSOR)
"""Роли субагентов шага (OQ-28: ровно две, обе low)."""

MAX_TASK_CALLS = 2
"""Предел вызовов `task` на шаг (OQ-28); дублируется в `RunLimits.max_subagent_calls`."""

_TASK_TOOL = "task"


# ------------------------------------------------------------------- схемы возврата


class CountryFact(BaseModel):
    """Один факт о стране с доказательством-цитатой."""

    topic: str = Field(description="тема факта: въезд, резидентство, часы, форма найма, валюта")
    statement: str = Field(description="факт одной фразой")
    quote: str = Field(description="точная цитата из результата инструмента")
    vacancy_id: str = Field(description="id вакансии, в чьих данных найдена цитата")


class CountryResearchResult(BaseModel):
    """Structured-возврат исследователя страны."""

    country: str = Field(description="страна, о которой собраны факты")
    findings: list[CountryFact] = Field(
        description="факты с цитатами; пусто, если ничего не нашлось"
    )
    gaps: list[str] = Field(description="чего в инструментах не нашлось, одной фразой на пункт")
    answer: str = Field(description="короткий вывод для основного агента")


class VacancyTrap(BaseModel):
    """Ловушка в условиях найма с цитатой-доказательством."""

    statement: str = Field(description="в чём ловушка, одной фразой")
    quote: str = Field(description="точная цитата из результата read_work_terms")
    vacancy_id: str = Field(description="id вакансии с этой ловушкой")


class VacancyVerdict(BaseModel):
    """Оценка одной вакансии по данным инструментов."""

    vacancy_id: str = Field(description="id вакансии из search_vacancies")
    title: str = Field(description="название вакансии")
    score: int = Field(description="балл 0–100 из score_vacancy, не выдуманный")
    recommendation: str = Field(description="рекомендация из score_vacancy и причина одной фразой")
    traps: list[VacancyTrap] = Field(description="ловушки с цитатами; пусто, если их нет")


class VacancyAssessmentResult(BaseModel):
    """Structured-возврат оценщика вакансий."""

    verdicts: list[VacancyVerdict] = Field(description="вердикт по каждой оценённой вакансии")
    gaps: list[str] = Field(description="чего не удалось оценить, одной фразой на пункт")
    answer: str = Field(description="короткий вывод для основного агента")


_ROLE_TOOLS: dict[str, tuple[str, ...]] = {
    COUNTRY_RESEARCHER: ("search_vacancies", "read_work_terms"),
    VACANCY_ASSESSOR: ("search_vacancies", "read_work_terms", "score_vacancy"),
}
"""Инструменты субагентов: узкие наборы из каталога `tools.py` (K-1 добавит свой)."""

_ROLE_RESPONSE: dict[str, type[BaseModel]] = {
    COUNTRY_RESEARCHER: CountryResearchResult,
    VACANCY_ASSESSOR: VacancyAssessmentResult,
}

_ROLE_PROMPT: dict[str, str] = {
    COUNTRY_RESEARCHER: "sub_research_country",
    VACANCY_ASSESSOR: "sub_assess_vacancies",
}

_ROLE_DESCRIPTION: dict[str, str] = {
    COUNTRY_RESEARCHER: (
        "Собирает, что известно о стране переезда: делает 2–4 вызова инструментов "
        "(поиск вакансий страны, условия найма) и возвращает факты о въезде, "
        "резидентстве, часах и форме найма с цитатами. Зови, когда шагу нужны "
        "факты о стране, а не оценка вакансии."
    ),
    VACANCY_ASSESSOR: (
        "Оценивает вакансии по профилю кандидата: делает 2–4 вызова инструментов "
        "(поиск, скоринг, условия найма) и возвращает вердикты с баллом, "
        "рекомендацией и ловушками с цитатами. Зови, когда нужно оценить конкретные "
        "вакансии или выбрать лучшую."
    ),
}


# ------------------------------------------------------------------- сборка спеков


def _clip(text: str, limit: int = 300) -> str:
    """Короткая сводка результата субагента для наблюдения шага."""
    flat = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _result_text(result: ToolMessage | Command[Any]) -> str:
    """Текст результата `task`: ToolMessage или Command с обновлением сообщений."""
    if isinstance(result, ToolMessage):
        content = result.content
    else:
        messages = (result.update or {}).get("messages") or []
        content = messages[-1].content if messages else ""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))


def build_subagent_specs(
    models: dict[str, BaseChatModel],
    ctx: ToolContext,
    recorder: StepRecorder,
    limits: RunLimits,
    observer: RunObserver | None,
) -> tuple[list[SubAgent], SubagentGate]:
    """Спеки субагентов шага и их наблюдатель-ограничитель (`SubagentGate`).

    Каждый субагент — изолированный (isolated): видит только делегированную задачу,
    свои инструменты и свой промпт; инструменты обёрнуты в запись шага с тегом роли.
    Роли без модели в `models` не объявляются — вызов `task` вернёт модели честный
    ответ «такого субагента нет».
    """
    specs: list[SubAgent] = []
    children: dict[str, StepRecorder] = {}
    for role in SUBAGENT_ROLES:
        model = models.get(role)
        if model is None:
            continue
        child = StepRecorder(recorder.step_id, recorder.index, emit=observer, subagent=role)
        children[role] = child
        tools = tuple(
            tool for name in _ROLE_TOOLS[role] if (tool := TOOL_BY_NAME.get(name)) is not None
        )
        spec: SubAgent = {
            "name": role,
            "description": _ROLE_DESCRIPTION[role],
            "system_prompt": load_prompt(_ROLE_PROMPT[role]),
            "model": model,
            "tools": to_langchain_tools(tools, ctx, child),
            "response_format": _ROLE_RESPONSE[role],
        }
        specs.append(spec)
    gate = SubagentGate(
        max_calls=limits.max_subagent_calls,
        recorder=recorder,
        children=children,
        observer=observer,
    )
    return specs, gate


class SubagentGate(AgentMiddleware):
    """Мидлварь исполнителя шага: лимит `task`-вызовов и события субагентов (A-8).

    Перехватывает вызов `task`: считает вызовы на шаг, третий и дальше отклоняет
    сообщением-данными (ошибка как наблюдение, не падение графа); успешный вызов
    дописывает в запись шага сводку результата, сливает вакансии, найденные внутри
    субагента, в состояние шага и отдаёт событие `tool_called` с тегом `subagent`.
    """

    def __init__(
        self,
        *,
        max_calls: int,
        recorder: StepRecorder,
        children: dict[str, StepRecorder],
        observer: RunObserver | None,
    ) -> None:
        self._max_calls = max_calls
        self._recorder = recorder
        self._children = children
        self._observer = observer
        self._used = 0

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Any,
    ) -> Any:
        call = request.tool_call
        if call.get("name") != _TASK_TOOL:
            return await handler(request)
        self._used += 1
        args = call.get("args") or {}
        role = str(args.get("subagent_type") or "?")
        call_id = str(call.get("id") or "")
        if self._used > self._max_calls:
            message = (
                f"лимит субагентов на шаг исчерпан ({self._max_calls}); "
                "продолжай шаг своими инструментами"
            )
            self._record_task(role, ok=False, text=message, error=message)
            return ToolMessage(
                content=json.dumps(
                    {
                        "error": {
                            "type": "busy",
                            "message": message,
                            "hint": "закончи шаг доступными инструментами",
                        }
                    },
                    ensure_ascii=False,
                ),
                tool_call_id=call_id,
            )
        result = await handler(request)
        text = _result_text(result)
        self._record_task(role, ok=True, text=text, error=None)
        return result

    def _record_task(self, role: str, *, ok: bool, text: str, error: str | None) -> None:
        """Сводка вызова `task` в запись шага и в поток событий."""
        summary = f"task({role}): {_clip(text)}"
        if ok:
            self._recorder.tools.append(_TASK_TOOL)
            self._recorder.summaries.append(summary)
            child = self._children.get(role)
            if child is not None:
                known = {str(v.get("id")) for v in self._recorder.vacancies if isinstance(v, dict)}
                for item in child.vacancies:
                    if isinstance(item, dict) and str(item.get("id")) not in known:
                        self._recorder.vacancies.append(item)
                        known.add(str(item.get("id")))
        else:
            self._recorder.last_error = self._recorder.last_error or error
        if self._observer is not None:
            payload: dict[str, Any] = {
                "step_id": self._recorder.step_id,
                "index": self._recorder.index,
                "tool": _TASK_TOOL,
                "subagent": role,
                "ok": ok,
                "summary": summary,
                "error": error,
            }
            self._observer.emit(AgentEvent(type="tool_called", payload=payload, node="step"))


__all__ = [
    "COUNTRY_RESEARCHER",
    "MAX_TASK_CALLS",
    "SUBAGENT_ROLES",
    "VACANCY_ASSESSOR",
    "SubagentGate",
    "build_subagent_specs",
]
