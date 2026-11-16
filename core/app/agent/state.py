"""Состояние запуска агента: цель, план, наблюдения, счётчики (A-1).

Состояние — один TypedDict на весь граф. Значения JSON-совместимы (pydantic-модели
поддерживаются сериализацией чекпойнтов langgraph), потому что состояние должно
переживать чекпойнты в Postgres (A-3).

План — список шагов со статусами, хранится в состоянии, а не в файлах deepagents:
узлы «план» и «перестройка» — явные узлы графа (решение по OQ-5/OQ-6, PLAN 3.1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field

StepStatus = Literal["todo", "done", "dropped"]
"""Статус шага плана. Пишут его узлы графа, не модель: модель отдаёт только данные шага."""

StopReason = Literal[
    "answered",
    "plan_exhausted",
    "step_limit",
    "replan_limit",
    "model_budget",
    "model_error",
    "model_schema",
]
"""Почему запуск остановился. `answered` — модель ответила по цели; остальное — честный
частичный результат (риски PLAN 4.1): предел шагов/перестроек/бюджета или сбой модели."""


class PlanStep(BaseModel):
    """Шаг плана в состоянии. `status` и `result` ведут узлы графа, модель их не шлёт."""

    model_config = {"frozen": True}

    id: str = Field(description="короткий id шага, s1, s2…")
    title: str = Field(description="короткое название шага")
    done_criteria: str = Field(description="признак, по которому шаг считается выполненным")
    status: StepStatus = "todo"
    result: str = ""  # краткое доказательство закрытия шага


class Observation(BaseModel):
    """Наблюдение одного шага: что вызвал исполнитель, что получил, чем закончил.

    Сырые результаты инструментов в состояние не складываются (история шага не тащится
    в следующий — риски PLAN 3.3): только короткие сводки и финальный текст шага.
    """

    model_config = {"frozen": True}

    step_id: str
    index: int = Field(description="номер шага в запуске, начиная с 1")
    tools: list[str] = Field(default_factory=list, description="какие инструменты вызвал шаг")
    summaries: list[str] = Field(default_factory=list, description="короткие сводки результатов")
    error: str | None = Field(default=None, description="последняя ошибка инструмента, если была")
    answer: str | None = Field(default=None, description="финальный текст шага от модели")


class AgentState(TypedDict):
    """Состояние запуска агента (критерий A-1, PLAN 4.1)."""

    # Цель и понимание цели
    goal: str
    note: str  # как агент понял цель (для экрана)

    # План и его история
    plan: list[PlanStep]
    plan_changes: list[dict[str, Any]]  # «было/стало» после перестроек (для экрана A-4)
    replan_reason: str | None  # причина последнего решения перестройки (для экрана A-4)

    # Позиция в плане
    current_step_id: str | None

    # Решение последней перестройки (маршрутное поле, читает ребро после `replan`)
    replan_action: Literal["continue", "rebuild", "finish"] | None

    # Наблюдения и собранное
    observations: list[Observation]
    vacancies: list[dict[str, Any]]  # найденные вакансии (из результатов инструментов)
    routes: list[dict[str, Any]]  # маршруты релокации (K-3; в каркасе пусто)
    pending_action: dict[str, Any] | None  # карточка действия, ждущего подтверждения (A-3)

    # Счётчики и пределы
    steps_taken: int
    replans_used: int
    model_calls: int
    tokens_in: int
    tokens_out: int
    failure_streak: int  # подряд идущие шаги с ошибкой

    # Итог
    answer: str | None
    stop_reason: StopReason | None
    error: str | None  # текст последнего сбоя модели, если был


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Пределы запуска (PLAN 3.1: шагов, перестроек, токенов; честный частичный итог).

    Выход за любой предел — не ошибка, а остановка с частичным результатом (A-1).
    """

    max_steps: int = 8  # исполненных шагов за запуск
    max_replans: int = 3  # перестроек плана за запуск
    max_model_calls: int = 40  # вызовов модели на запуск, включая вызовы внутри шага
    max_tokens: int = 200_000  # суммарных токенов вход+выход на запуск
    max_failure_streak: int = 2  # подряд идущих неудачных шагов до передачи перестройке
    max_subagent_calls: int = 2  # вызовов `task` (субагентов) на шаг (OQ-28)
    step_max_turns: int = 4  # ходов модели внутри одного шага (маленький ReAct, OQ-6)
    plan_min_steps: int = 2
    plan_max_steps: int = 6

    @property
    def step_recursion_limit(self) -> int:
        """Потолок узлов внутреннего графа шага: на каждый ход — модель + инструменты."""
        return self.step_max_turns * 2 + 4


def first_todo_step(plan: list[PlanStep]) -> PlanStep | None:
    """Первый незакрытый шаг плана или `None`, если план кончился."""
    for step in plan:
        if step.status == "todo":
            return step
    return None


def render_plan(plan: list[PlanStep]) -> str:
    """План одним текстом для промпта: id, статус, название, критерий."""
    marks = {"todo": "—", "done": "✓", "dropped": "×"}
    lines = []
    for step in plan:
        criteria = f"; критерий: {step.done_criteria}" if step.done_criteria else ""
        result = f"; итог: {step.result}" if step.result else ""
        lines.append(f"[{marks[step.status]}] {step.id}. {step.title}{criteria}{result}")
    return "\n".join(lines) if lines else "(план пуст)"


def apply_replan(plan: list[PlanStep], updates: list[dict[str, Any]]) -> list[PlanStep]:
    """Актуальный план из ответа перестройки (правка по id, PLAN 3.1).

    Существующий id: обновляются title/done_criteria; статус управляется перестройкой,
    но `done` назад в `todo` не откатывается. Новый id — новый шаг в `todo`. Шаги,
    которых нет в ответе, считаются отброшенными (`dropped`), а не удалёнными — история
    плана для экрана важнее чистоты списка.
    """
    update_by_id = {str(u.get("id", "")): u for u in updates}
    result: list[PlanStep] = []
    for step in plan:
        update = update_by_id.get(step.id)
        if update is None:
            if step.status != "dropped":
                step = step.model_copy(update={"status": "dropped"})
            result.append(step)
            continue
        raw_status = update.get("status", step.status)
        new_status: StepStatus = (
            raw_status if raw_status in ("todo", "done", "dropped") else step.status
        )
        if step.status == "done":
            new_status = "done"  # закрытый шаг не откатывается
        result.append(
            step.model_copy(
                update={
                    "title": str(update.get("title", step.title)),
                    "done_criteria": str(update.get("done_criteria", step.done_criteria)),
                    "status": new_status,
                }
            )
        )
        update_by_id.pop(step.id)
    for new_id, update in update_by_id.items():
        if not new_id or any(s.id == new_id for s in result):
            continue
        result.append(
            PlanStep(
                id=new_id,
                title=str(update.get("title", "")),
                done_criteria=str(update.get("done_criteria", "")),
                status="todo" if update.get("status", "todo") != "dropped" else "dropped",
            )
        )
    return result


def plan_diff(before: list[PlanStep], after: list[PlanStep]) -> dict[str, Any]:
    """Короткая запись «было/стало» для экрана (A-4): id, статус, что поменялось."""
    before_by_id = {s.id: s for s in before}
    changes: list[str] = []
    for step in after:
        old = before_by_id.get(step.id)
        if old is None:
            changes.append(f"+ {step.id}: {step.title}")
        elif old.status != step.status:
            changes.append(f"~ {step.id}: {old.status} → {step.status}")
        elif old.title != step.title or old.done_criteria != step.done_criteria:
            changes.append(f"~ {step.id}: {old.title} → {step.title}")
    for step in before:
        if step.id not in {s.id for s in after}:
            changes.append(f"- {step.id}: {step.title}")
    return {
        "was": [s.model_dump() for s in before],
        "now": [s.model_dump() for s in after],
        "changes": changes,
    }


def plan_has_open_steps(plan: list[PlanStep]) -> bool:
    """Остались ли в плане шаги в `todo`."""
    return any(step.status == "todo" for step in plan)


def done_steps_summary(plan: list[PlanStep], observations: list[Observation]) -> str:
    """Человеческая сводка «что удалось» для честного частичного результата."""
    lines: list[str] = []
    for step in plan:
        if step.status != "done":
            continue
        line = f"- {step.title}"
        obs = next((o for o in reversed(observations) if o.step_id == step.id), None)
        if obs and obs.answer:
            line += f": {obs.answer}"
        elif step.result:
            line += f": {step.result}"
        lines.append(line)
    return "\n".join(lines) if lines else "(шаги не закрыты)"


STOP_REASONS_TEXT: dict[str, str] = {
    "step_limit": "исчерпан лимит шагов запуска",
    "replan_limit": "исчерпан лимит перестроек плана",
    "model_budget": "исчерпан бюджет вызовов/токенов запуска",
    "model_error": "модель не ответила",
    "model_schema": "модель не смогла отдать ответ в нужном формате",
    "plan_exhausted": "план кончился раньше, чем цель закрылась",
}
