"""События запуска агента (A-3): типы, наблюдатель, соглашение о payload.

Событие — то, что уходит в Postgres (`agent_events`) и в SSE-поток запуска: экран
строит ход работы по событиям без опроса, а таймеры узлов (`node_timing`) дают
метрику p90 шага (OQ-29, порог 60 с). `judge_verdict` (A-5) — вердикт судьи:
самопроверка шага (level=step) и проверка итога (level=final), `{verdict, reason}`.
Расход (E-9): `run_started` несёт пределы (`limits`), `node_timing` и терминальные
события — снимок `usage` (вызовы модели, токены, цена, разбивка по группам).

Наблюдатель — синхронный колбэк `emit`: узлы графа вызывают его из одного event loop,
а менеджер запуска (`runs.py`) перекладывает события в хранилище и подписчикам SSE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

EventType = Literal[
    "run_started",
    "plan_created",
    "step_started",
    "tool_called",
    "observation",
    "plan_changed",
    "step_checked",
    "judge_verdict",
    "needs_confirmation",
    "confirmation_resolved",
    "node_timing",
    "done",
    "failed",
    "cancelled",
]
"""Типы событий запуска."""


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Одно событие запуска: тип, данные, узел-источник и время узла."""

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    node: str | None = None
    duration_ms: float | None = None


class RunObserver(Protocol):
    """Синхронный наблюдатель событий (pump менеджера запусков, тестовый собиратель).

    `emit` вызывается из того же event loop, что и узлы графа, поэтому без await:
    наблюдатель лишь кладёт событие в очередь (pump пишет в Postgres и раздаёт SSE).
    """

    def emit(self, event: AgentEvent) -> None: ...


def node_event(
    node: str,
    duration_ms: float,
    *,
    paused: bool = False,
    usage: dict[str, Any] | None = None,
) -> AgentEvent:
    """Таймер узла для метрики p90 (OQ-29): узел целиком, не только вызов модели.

    `usage` (E-9) — расход запуска на конец узла (`RunBudget.snapshot`): экран берёт
    последний снимок, разница соседних снимков — расход одного узла.
    """
    payload: dict[str, Any] = {"node": node, "paused": paused}
    if usage is not None:
        payload["usage"] = usage
    return AgentEvent(
        type="node_timing",
        payload=payload,
        node=node,
        duration_ms=round(duration_ms, 1),
    )


__all__ = ["AgentEvent", "EventType", "RunObserver", "node_event"]
