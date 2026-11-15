"""Каркас агента на deepagents (A-1).

Публичный слой: состояние, пределы, сборка графа и запуск по цели. Узлы — план, шаг,
проверка, перестройка, финал; чекпойнтер — снаружи (MemorySaver в тестах, Postgres в A-3).
"""

from core.app.agent.budget import RunBudget
from core.app.agent.checkpoints import memory_checkpointer, open_postgres_checkpointer
from core.app.agent.executor import step_node
from core.app.agent.graph import AgentDeps, build_agent_graph, default_deps, run_agent_goal
from core.app.agent.planner import PlanSpec, planner_node
from core.app.agent.replanner import ReplanSpec, replan_node
from core.app.agent.state import (
    AgentState,
    Observation,
    PlanStep,
    RunLimits,
    StepStatus,
    StopReason,
    apply_replan,
    plan_diff,
    render_plan,
)

__all__ = [
    "AgentDeps",
    "AgentState",
    "Observation",
    "PlanSpec",
    "PlanStep",
    "ReplanSpec",
    "RunBudget",
    "RunLimits",
    "StepStatus",
    "StopReason",
    "apply_replan",
    "build_agent_graph",
    "default_deps",
    "memory_checkpointer",
    "open_postgres_checkpointer",
    "plan_diff",
    "planner_node",
    "render_plan",
    "replan_node",
    "run_agent_goal",
    "step_node",
]
