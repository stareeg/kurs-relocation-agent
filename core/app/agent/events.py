"""События запуска агента (A-3): типы, наблюдатель, соглашение о payload.

Событие — то, что уходит в Postgres (`agent_events`) и в SSE-поток запуска: экран
строит ход работы по событиям без опроса, а таймеры узлов (`node_timing`) дают
метрику p90 шага (OQ-29, порог 60 с). `judge_verdict` резервируется за судьёй (A-5).

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
    "needs_confirmation",
    "confirmation_resolved",
    "node_timing",
    "done",
    "failed",
]
"""Типы событий запуска. `judge_verdict` придёт с A-5 и дополнит список."""


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


def node_event(node: str, duration_ms: float, *, paused: bool = False) -> AgentEvent:
    """Таймер узла для метрики p90 (OQ-29): узел целиком, не только вызов модели."""
    return AgentEvent(
        type="node_timing",
        payload={"node": node, "paused": paused},
        node=node,
        duration_ms=round(duration_ms, 1),
    )


__all__ = ["AgentEvent", "EventType", "RunObserver", "node_event"]
