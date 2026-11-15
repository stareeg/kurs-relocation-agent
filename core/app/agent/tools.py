"""Мост между контрактами инструментов из `agent/` и циклом deepagents (A-1, OQ-5).

Контракты ДЗ1 переиспользуются: `Tool` (имя, схема аргументов, kind), `ToolContext`
(сессия, права, подтверждения) и `execute_tool` (валидация, подтверждение, ретраи, сбои).
Адаптер оборачивает каждый контракт в `StructuredTool`, который deepagents скармливает
модели, и собирает факты шага для состояния: сводки, ошибки, найденные вакансии,
карточка подтверждения.

Самописный минимальный цикл из `agent/loop.py` сюда не переносится: циклом шага
управляет deepagents (решение 15.11), цикл ДЗ1 удаляется после переноса (A-2).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from langchain_core.tools import StructuredTool

from agent.contracts import (
    ConfirmationCard,
    Tool,
    ToolCall,
    ToolContext,
    error_payload,
    short,
)
from agent.tools import execute_tool
from core.app.agent.state import Observation


class StepRecorder:
    """Копилка фактов одного шага: результаты инструментов, ошибки, вакансии, карточка.

    Один экземпляр на запуск шага; заполняется обёртками инструментов, вычитается узлом
    шага в состояние (`Observation`, `vacancies`, `pending_action`).
    """

    def __init__(self, step_id: str, index: int) -> None:
        self.step_id = step_id
        self.index = index
        self.tools: list[str] = []
        self.summaries: list[str] = []
        self.last_error: str | None = None
        self.vacancies: list[dict[str, Any]] = []
        self.pending: ConfirmationCard | None = None

    def record(
        self,
        tool: Tool,
        result: dict[str, Any],
        error: dict[str, Any] | None,
    ) -> None:
        """Запомнить один вызов: имя, короткую сводку, ошибку, вакансии."""
        self.tools.append(tool.name)
        if error is not None:
            message = str(error.get("message", "ошибка инструмента"))
            self.summaries.append(f"{tool.name}: ошибка — {message}")
            self.last_error = message
            return
        self.summaries.append(f"{tool.name}: {short(result)}")
        items = result.get("items")
        if isinstance(items, list):
            known = {str(v.get("id")) for v in self.vacancies if isinstance(v, dict)}
            for item in items:
                if isinstance(item, dict) and str(item.get("id")) not in known:
                    self.vacancies.append(item)
                    known.add(str(item.get("id")))

    def record_pending(self, card: ConfirmationCard) -> bool:
        """Действие ждёт подтверждения: карточка уходит в состояние, выполнения нет.

        В A-1 подтверждение модели не отдаётся (решение остаётся за человеком, A-3
        переведёт это в interrupt/resume), поэтому хук всегда отвечает «нет».
        """
        self.pending = card
        return False

    def to_observation(self, answer: str | None) -> Observation:
        return Observation(
            step_id=self.step_id,
            index=self.index,
            tools=list(self.tools),
            summaries=list(self.summaries),
            error=self.last_error,
            answer=answer,
        )


def build_run_context(base: ToolContext, recorder: StepRecorder) -> ToolContext:
    """Контекст запуска: тот же сессия/права/сбои, но хук подтверждения пишет карточку."""
    return dataclasses.replace(base, confirm=recorder.record_pending)


def to_langchain_tools(
    tools: tuple[Tool, ...],
    ctx: ToolContext,
    recorder: StepRecorder,
) -> list[StructuredTool]:
    """Контракты ДЗ1 → инструменты для deepagents (та же схема аргументов, тот же execute_tool)."""

    def make_runner(tool: Tool) -> Any:
        async def run(**kwargs: Any) -> str:
            call_id = f"{tool.name}-{recorder.index}-{len(recorder.tools) + 1}"
            call = ToolCall(id=call_id, name=tool.name, arguments=kwargs)
            result, error, _confirmed_by = execute_tool(call, ctx)
            error_dict = error_payload(error) if error is not None else None
            recorder.record(tool, result, error_dict)
            return json.dumps(error_dict if error_dict is not None else result, ensure_ascii=False)

        return run

    return [
        StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_model,
            coroutine=make_runner(tool),
        )
        for tool in tools
    ]


__all__ = ["StepRecorder", "build_run_context", "to_langchain_tools"]
