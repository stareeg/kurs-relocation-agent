"""LLM-слой ядра: кастомный OpenRouter-чат с тирами, cost-учётом и structured output."""

from core.platform.llm.budget import KIND_PRIORITY, BudgetFit, InputBlock, fit_blocks
from core.platform.llm.call import CallContext, ImageInput, run
from core.platform.llm.contract import check_all_features_contract, check_feature_contract
from core.platform.llm.openrouter_chat import (
    OpenRouterChatModel,
    OpenRouterConnectionError,
    OpenRouterError,
    OpenRouterRateLimitError,
    OpenRouterResponseError,
    get_chat_model,
)
from core.platform.llm.prompt_cache import build_cached_system_prompt, supports_cache_control
from core.platform.llm.registry import (
    LlmFeature,
    all_features,
    chat_model_for,
    ensure_features_loaded,
    get_feature,
    register,
    require_feature,
    resolve_tier,
)
from core.platform.llm.usage import (
    NoopUsageSink,
    UsageFact,
    UsageRecord,
    UsageSink,
    compute_cost,
    default_usage_sink,
    emit_usage,
    today_llm_budget,
)

__all__ = [
    "OpenRouterChatModel",
    "get_chat_model",
    "chat_model_for",
    "run",
    "CallContext",
    "ImageInput",
    "fit_blocks",
    "InputBlock",
    "BudgetFit",
    "KIND_PRIORITY",
    "check_feature_contract",
    "check_all_features_contract",
    "LlmFeature",
    "register",
    "get_feature",
    "require_feature",
    "all_features",
    "resolve_tier",
    "ensure_features_loaded",
    "OpenRouterError",
    "OpenRouterRateLimitError",
    "OpenRouterConnectionError",
    "OpenRouterResponseError",
    "build_cached_system_prompt",
    "supports_cache_control",
    "NoopUsageSink",
    "UsageSink",
    "UsageRecord",
    "UsageFact",
    "compute_cost",
    "default_usage_sink",
    "emit_usage",
    "today_llm_budget",
]
