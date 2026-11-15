"""Бюджет запуска агента: вызовы модели и токены по всему запуску (A-1).

Счётчик — колбэк-обработчик: он видит и вызовы узлов графа, и вызовы внутри шага
(исполнитель deepagents зовёт модель сам), потому что колбэки наследуются по всему
дереву запуска. Предел проверяется узлами между фазами; выход за предел — не ошибка,
а остановка с честным частичным результатом (`state.stop_reason = "model_budget"`).
"""

from __future__ import annotations

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig

from core.app.agent.state import RunLimits


class RunBudget(BaseCallbackHandler):
    """Счётчик вызовов модели и токенов одного запуска графа.

    Один экземпляр на запуск: создаётся в `run_agent_goal`, идёт в `config`
    и как колбэк, и в `configurable` — узлы читают totals после своих фаз.
    """

    def __init__(self, limits: RunLimits) -> None:
        self.limits = limits
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def on_chat_model_start(self, serialized: Any, messages: list[Any], **kwargs: Any) -> None:
        self.calls += 1

    def on_chat_model_end(self, response: LLMResult, **kwargs: Any) -> None:
        usage = (response.llm_output or {}).get("usage") or {}
        self.tokens_in += int(usage.get("prompt_tokens") or 0)
        self.tokens_out += int(usage.get("completion_tokens") or 0)

    def over_call_budget(self) -> bool:
        return self.calls >= self.limits.max_model_calls

    def over_token_budget(self) -> bool:
        return self.tokens_in + self.tokens_out >= self.limits.max_tokens

    def over_budget(self) -> bool:
        return self.over_call_budget() or self.over_token_budget()


class _NoopBudget(RunBudget):
    """Заглушка для прямых вызовов узлов без конфига (юнит-тесты переходов)."""

    def __init__(self) -> None:
        super().__init__(limits=RunLimits())

    def on_chat_model_start(self, serialized: Any, messages: list[Any], **kwargs: Any) -> None:
        return

    def on_chat_model_end(self, response: LLMResult, **kwargs: Any) -> None:
        return

    def over_budget(self) -> bool:
        return False


_BUDGET_KEY = "run_budget"
"""Ключ бюджета в `configurable`; туда же объект идёт колбэком."""


def put_budget(config: RunnableConfig, budget: RunBudget) -> RunnableConfig:
    """Вписать бюджет в конфиг запуска: колбэком (счёт) и в configurable (чтение)."""
    existing = config.get("callbacks")
    callbacks = list(existing) if isinstance(existing, list) else []
    callbacks.append(budget)
    configurable = dict(config.get("configurable") or {})
    configurable[_BUDGET_KEY] = budget
    return {**config, "callbacks": callbacks, "configurable": configurable}


def budget_from(config: RunnableConfig | None) -> RunBudget:
    """Бюджет из конфига узла; без конфига — заглушка, которая ничего не считает."""
    if config is None:
        return _NoopBudget()
    budget = (config.get("configurable") or {}).get(_BUDGET_KEY)
    if isinstance(budget, RunBudget):
        return budget
    return _NoopBudget()


__all__ = ["RunBudget", "put_budget", "budget_from"]
