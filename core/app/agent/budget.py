"""Бюджет запуска агента: вызовы модели, токены и цена по всему запуску (A-1, E-9).

Счётчик — колбэк-обработчик: он видит и вызовы узлов графа, и вызовы внутри шага
(исполнитель deepagents зовёт модель сам), и LLM-фичи внутри инструментов (условия
найма, письмо), потому что колбэки наследуются по всему дереву запуска. Предел
проверяется узлами между фазами; выход за предел — не ошибка, а остановка с честным
частичным результатом (`state.stop_reason = "model_budget"`).

Ответ чат-модели LangChain отдаёт в `on_llm_end`: отдельного `on_chat_model_end` у
колбэков нет. До E-9 счётчик слушал именно его, поэтому токены запуска всегда были нулём
на любом маршруте. Токены берутся из `usage_metadata` сообщения (так их кладёт наша
`OpenRouterChatModel` и любой чат-модель LangChain), запасной путь — `llm_output`
(`usage` у нашей модели, `token_usage` у `ChatOpenAI`). Цена — `cost_usd` вызова (реальная
цена OpenRouter или прайс `MODEL_PRICES`); у моделей своей ВМ (`SELF_HOSTED_MODELS`) это
условная цена по прайсу OpenRouter, она считается отдельно, чтобы экран не выдавал её за
потраченные деньги.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableConfig

from core.app.agent.llm import AGENT_PLAN, AGENT_REPLAN, AGENT_STEP
from core.app.agent.state import RunLimits

USAGE_GROUPS = ("agent", "subagents", "judge", "tools")
"""Кто тратит вызовы: узлы агента, субагенты шага, судья, LLM-фичи внутри инструментов."""

_AGENT_FEATURES = frozenset({AGENT_PLAN, AGENT_STEP, AGENT_REPLAN})


def feature_group(feature: str) -> str:
    """Фича LLM → группа расхода для панели и разбора бюджета."""
    if feature in _AGENT_FEATURES:
        return "agent"
    if feature.startswith("agent_sub_"):
        return "subagents"
    if feature.startswith("agent_judge_"):
        return "judge"
    return "tools"


def _self_hosted_models() -> frozenset[str]:
    from core.config import get_settings, normalize_openrouter_model

    names = getattr(get_settings(), "self_hosted_models", None) or []
    return frozenset(normalize_openrouter_model(str(name)) for name in names)


def usage_of(response: LLMResult) -> tuple[int, int, float | None, str]:
    """Токены вход/выход, цена (если модель её сообщила) и имя модели одного ответа."""
    tokens_in = tokens_out = 0
    cost: float | None = None
    model = ""
    found = False
    for generations in response.generations:
        for generation in generations:
            message = getattr(generation, "message", None)
            meta = getattr(message, "usage_metadata", None)
            if meta:
                tokens_in += int(meta.get("input_tokens") or 0)
                tokens_out += int(meta.get("output_tokens") or 0)
                found = True
            info = {
                **(generation.generation_info or {}),
                **(getattr(message, "response_metadata", None) or {}),
            }
            if info.get("cost_usd") is not None:
                cost = (cost or 0.0) + float(info["cost_usd"])
            model = model or str(info.get("model") or info.get("model_name") or "")
    output = response.llm_output or {}
    if not found:
        usage = output.get("usage") or output.get("token_usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
    if cost is None and output.get("cost_usd") is not None:
        cost = float(output["cost_usd"])
    model = model or str(output.get("model") or output.get("model_name") or "")
    return tokens_in, tokens_out, cost, model


def _empty_bucket() -> dict[str, Any]:
    return {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}


class RunBudget(BaseCallbackHandler):
    """Счётчик вызовов модели, токенов и цены одного запуска графа.

    Один экземпляр на запуск: создаётся в `run_agent_goal`/менеджере, идёт в `config`
    и как колбэк, и в `configurable` — узлы читают totals после своих фаз.
    `run_inline`: счёт идёт в потоке event loop, без пересадки в пул потоков.
    """

    run_inline = True
    counting = True

    def __init__(self, limits: RunLimits, *, self_hosted: frozenset[str] | None = None) -> None:
        self.limits = limits
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.cost_self_hosted_usd = 0.0
        self.by_group: dict[str, dict[str, Any]] = {g: _empty_bucket() for g in USAGE_GROUPS}
        self._self_hosted = self_hosted
        self._groups: dict[UUID, str] = {}

    def _is_self_hosted(self, model: str) -> bool:
        if self._self_hosted is None:
            self._self_hosted = _self_hosted_models()
        if not model or not self._self_hosted:
            return False
        from core.config import normalize_openrouter_model

        return normalize_openrouter_model(model) in self._self_hosted

    def on_chat_model_start(
        self,
        serialized: Any,
        messages: list[Any],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.calls += 1
        group = feature_group(str((metadata or {}).get("agent") or ""))
        self._groups[run_id] = group
        self.by_group[group]["calls"] += 1

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        group = self._groups.pop(run_id, "tools")
        tokens_in, tokens_out, cost, model = usage_of(response)
        if cost is None:
            cost = 0.0
            if tokens_in or tokens_out:
                from core.platform.llm.usage import compute_cost

                cost = compute_cost(model, tokens_in, tokens_out)
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.cost_usd += cost
        if self._is_self_hosted(model):
            self.cost_self_hosted_usd += cost
        bucket = self.by_group[group]
        bucket["tokens_in"] += tokens_in
        bucket["tokens_out"] += tokens_out
        bucket["cost_usd"] += cost

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._groups.pop(run_id, None)

    def over_call_budget(self) -> bool:
        return self.calls >= self.limits.max_model_calls

    def over_token_budget(self) -> bool:
        return self.tokens_in + self.tokens_out >= self.limits.max_tokens

    def over_budget(self) -> bool:
        return self.over_call_budget() or self.over_token_budget()

    def snapshot(self) -> dict[str, Any]:
        """Расход запуска для событий, состояния и строки `agent_runs.usage` (E-9)."""
        return {
            "model_calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": round(self.cost_usd, 6),
            "cost_self_hosted_usd": round(self.cost_self_hosted_usd, 6),
            "by_group": {
                group: {**bucket, "cost_usd": round(float(bucket["cost_usd"]), 6)}
                for group, bucket in self.by_group.items()
            },
        }

    def state_update(self) -> dict[str, Any]:
        """Счётчики для возврата узла: пределы читают плоские поля, экран — `usage`."""
        return {
            "model_calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "usage": self.snapshot(),
        }

    def restore(self, values: Mapping[str, Any]) -> None:
        """Продолжить счёт с чекпойнта (резюм после паузы, итог отмены после рестарта)."""
        usage = values.get("usage") or {}
        self.calls = int(values.get("model_calls") or usage.get("model_calls") or 0)
        self.tokens_in = int(values.get("tokens_in") or usage.get("tokens_in") or 0)
        self.tokens_out = int(values.get("tokens_out") or usage.get("tokens_out") or 0)
        self.cost_usd = float(usage.get("cost_usd") or 0.0)
        self.cost_self_hosted_usd = float(usage.get("cost_self_hosted_usd") or 0.0)
        saved = usage.get("by_group") or {}
        for group in USAGE_GROUPS:
            bucket = saved.get(group) or {}
            self.by_group[group] = {
                "calls": int(bucket.get("calls") or 0),
                "tokens_in": int(bucket.get("tokens_in") or 0),
                "tokens_out": int(bucket.get("tokens_out") or 0),
                "cost_usd": float(bucket.get("cost_usd") or 0.0),
            }


class _NoopBudget(RunBudget):
    """Заглушка для прямых вызовов узлов без конфига (юнит-тесты переходов)."""

    counting = False

    def __init__(self) -> None:
        super().__init__(limits=RunLimits(), self_hosted=frozenset())

    def on_chat_model_start(self, serialized: Any, messages: list[Any], **kwargs: Any) -> None:
        return

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        return

    def over_budget(self) -> bool:
        return False


def run_limits_payload(limits: RunLimits) -> dict[str, int]:
    """Пределы, которые экран показывает рядом с расходом («шаги N из 8»)."""
    return {
        "max_steps": limits.max_steps,
        "max_model_calls": limits.max_model_calls,
        "max_tokens": limits.max_tokens,
    }


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


__all__ = [
    "USAGE_GROUPS",
    "RunBudget",
    "budget_from",
    "feature_group",
    "put_budget",
    "run_limits_payload",
    "usage_of",
]
