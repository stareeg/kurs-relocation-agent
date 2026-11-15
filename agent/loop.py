"""Цикл агента: рассуждение → действие → наблюдение, с лимитом шагов.

Модель решает, какой инструмент вызвать; всё остальное делает код: проверяет аргументы,
спрашивает человека перед действием, ограничивает число шагов и повторных вызовов, пишет журнал.
"""

from __future__ import annotations

import json
from collections import Counter

from agent.contracts import AgentRun, Step, ToolCall, ToolContext, ToolError
from agent.providers import Provider, ProviderTurn
from agent.tools import TOOLS, execute_tool

SYSTEM_PROMPT = """Ты агент по поиску удалённой работы за рубежом.

Правила:
1. Не выдумывай данные: вакансии и правила стран бери только из инструментов.
2. Сначала ищи вакансии, потом при необходимости проверяй правила страны.
3. Отправляй отклик только на вакансию, которую вернул search_vacancies, и только когда
   человек попросил отправить. Отклик — действие: код сам покажет карточку подтверждения.
4. Если инструмент вернул ошибку, не придумывай результат. Попробуй другой способ или честно
   скажи, что данных нет и что нужно сделать.
5. В конце ответа перечисли, что нашли, какие условия проверили и что отправили.
   Отвечай по-русски, коротко и по делу."""

_REPEAT_LIMIT = 3


def _parse_args(call: ToolCall) -> str:
    return (
        call.arguments
        if isinstance(call.arguments, str)
        else json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)
    )


def run_agent(
    goal: str,
    provider: Provider,
    *,
    context: ToolContext | None = None,
    max_steps: int = 6,
) -> AgentRun:
    """Один прогон агента. Возвращает ответ, журнал шагов и причину остановки."""
    ctx = context or ToolContext()
    messages: list[dict[str, object]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": goal},
    ]
    schemas = [tool.schema() for tool in TOOLS]
    steps: list[Step] = []
    seen: Counter[str] = Counter()
    tokens_in = 0
    tokens_out = 0

    for index in range(1, max_steps + 1):
        turn: ProviderTurn = provider.complete(messages, schemas)
        tokens_in += turn.tokens_in
        tokens_out += turn.tokens_out
        messages.append(turn.as_message())

        if not turn.tool_calls:
            return AgentRun(
                answer=turn.content or "",
                steps=steps,
                stop_reason="answered",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                seen_calls=seen,
            )

        for call in turn.tool_calls:
            key = f"{call.name}:{_parse_args(call)}"
            seen[key] += 1
            if seen[key] >= _REPEAT_LIMIT:
                return AgentRun(
                    answer=(
                        "Передаю оператору: агент три раза подряд вызвал один и тот же "
                        f"инструмент ({call.name}). Нужен человек."
                    ),
                    steps=steps,
                    stop_reason="loop_guard",
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    seen_calls=seen,
                )

            result, error, confirmed_by = execute_tool(call, ctx)
            steps.append(
                Step(
                    index=index,
                    tool=call.name,
                    args=call.arguments
                    if isinstance(call.arguments, dict)
                    else {"raw": call.arguments},
                    result=result,
                    error=error,
                    confirmed_by=confirmed_by,
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return AgentRun(
        answer=(
            f"Передаю оператору: за {max_steps} шагов агент не закончил задачу. "
            "Последние действия — в журнале."
        ),
        steps=steps,
        stop_reason="step_limit",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        seen_calls=seen,
    )


def error_of(step: Step) -> ToolError | None:
    """Ошибка шага, если была нужна вызывающей стороне (демо, тесты)."""
    return step.error
