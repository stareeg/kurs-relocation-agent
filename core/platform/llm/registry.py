"""Реестр LLM-фич: тир/промпт/бюджет рядом с кодом, не в AGENT_TIER_MAP.

Декларации живут в `core.domains.*.llm` и регистрируются на импорте модуля.
Имена моделей — только в `.env` (`MODEL_TIER_*`); узкий тюнинг — `AGENT_TIER_OVERRIDES`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.platform.llm.openrouter_chat import TIERS, OpenRouterChatModel, get_chat_model

# Имя по умолчанию у complete_* без явного agent= — не продуктовая фича.
_SYSTEM_ALIAS = "system"

_LOADED = False

# OpenRouter reasoning.effort. None в декларации — не слать reasoning вовсе (быстрее).
# "none" — явно выключить reasoning у моделей, которые иначе думают по умолчанию (Qwen 3.8
# Flash, DeepSeek V4 Flash и прочие «мыслящие по дефолту»). Уходит в запрос не как
# `effort: "none"` (такого значения у OpenRouter нет), а как `reasoning.enabled = false` —
# см. `openrouter_chat._build_payload`.
REASONING_EFFORTS = frozenset({"none", "low", "medium", "high"})


@dataclass(frozen=True, slots=True)
class LlmFeature:
    """Декларация одной LLM-фичи.

    `tier` — имя тира (`advanced`/`basic`/`reserve`), не slug модели.
    `prompt` — путь к `.md` относительно корня репо; `None` + `prompt_in_code=True`,
    если system/user собираются в коде домена.
    `schema` — Pydantic-модель structured-выхода; иначе текст/динамическая схема.
    `budget_ms` — SLO таймаута вызова (обязателен по контракту A-09).
    `max_tokens` — потолок выхода (обязателен по контракту).
    `retries` — ремонты structured/схемы; канон L-13 = 1 (итого ≤2 LLM-вызова).
    `reasoning_effort` — OpenRouter effort по фиче, не по тиру; None = без reasoning.
    """

    name: str
    tier: str
    prompt: str | None = None
    schema: type | None = None
    max_tokens: int | None = None
    cache_prefix: bool = False
    budget_ms: int | None = None
    temperature: float | None = None
    retries: int | None = None
    prompt_in_code: bool = False
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise ValueError(
                f"LlmFeature {self.name!r}: неизвестный тир {self.tier!r}, ожидали один из {TIERS}"
            )
        if not self.name or self.name in TIERS:
            raise ValueError(f"LlmFeature: имя {self.name!r} нельзя — пустое или совпадает с тиром")
        if self.prompt_in_code and self.prompt:
            raise ValueError(
                f"LlmFeature {self.name!r}: нельзя одновременно prompt и prompt_in_code"
            )
        if self.budget_ms is not None and self.budget_ms <= 0:
            raise ValueError(
                f"LlmFeature {self.name!r}: budget_ms должен быть > 0, сейчас {self.budget_ms!r}"
            )
        if self.max_tokens is not None and self.max_tokens < 1024:
            raise ValueError(
                f"LlmFeature {self.name!r}: max_tokens должен быть ≥ 1024, "
                f"сейчас {self.max_tokens!r}"
            )
        if self.retries is not None and self.retries < 0:
            raise ValueError(
                f"LlmFeature {self.name!r}: retries должен быть ≥ 0, сейчас {self.retries!r}"
            )
        if self.reasoning_effort is not None and self.reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(
                f"LlmFeature {self.name!r}: reasoning_effort={self.reasoning_effort!r}, "
                f"ожидали один из {sorted(REASONING_EFFORTS)} или None"
            )


_REGISTRY: dict[str, LlmFeature] = {}


def register(feature: LlmFeature) -> LlmFeature:
    """Зарегистрировать фичу. Повтор с тем же содержимым — ok; конфликт полей — ошибка."""
    existing = _REGISTRY.get(feature.name)
    if existing is not None and existing != feature:
        raise ValueError(
            f"LLM-фича {feature.name!r} уже зарегистрирована с другими параметрами: "
            f"{existing} vs {feature}"
        )
    _REGISTRY[feature.name] = feature
    return feature


def get_feature(name: str) -> LlmFeature | None:
    ensure_features_loaded()
    return _REGISTRY.get(name)


def require_feature(name: str) -> LlmFeature:
    feature = get_feature(name)
    if feature is None:
        known = ", ".join(sorted(_REGISTRY)) or "(пусто)"
        raise KeyError(
            f"LLM-фича {name!r} не зарегистрирована. "
            f"Добавь LlmFeature в domains/*/llm.py. Известные: {known}"
        )
    return feature


def all_features() -> tuple[LlmFeature, ...]:
    ensure_features_loaded()
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))


def resolve_tier(name: str, *, settings: Any | None = None) -> str:
    """Тир фичи: `AGENT_TIER_OVERRIDES` → декларация → ошибка (без тихого fallback на agent)."""
    from core.config import get_settings

    ensure_features_loaded()
    cfg = settings or get_settings()
    overrides = getattr(cfg, "agent_tier_overrides", None) or {}
    if name in overrides:
        tier = str(overrides[name])
        return tier if tier in TIERS else "basic"

    if name == _SYSTEM_ALIAS:
        return "basic"

    feature = _REGISTRY.get(name)
    if feature is None:
        known = ", ".join(sorted(_REGISTRY)) or "(пусто)"
        raise KeyError(
            f"LLM-фича {name!r} не в реестре — тир неизвестен. "
            f"Раньше AGENT_TIER_MAP тихо откатывал на agent; теперь нужна декларация. "
            f"Известные: {known}"
        )
    return feature.tier


def chat_model_for(
    name: str,
    *,
    settings: Any | None = None,
    usage_sink: Any | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tier_override: str | None = None,
    model_override: str | None = None,
    **kwargs: Any,
) -> OpenRouterChatModel:
    """Фабрика чат-модели по имени фичи из реестра (единственный вход для доменов)."""
    feature = require_feature(name)
    from core.config import get_settings

    cfg = settings or get_settings()
    if tier_override and tier_override in TIERS:
        tier = tier_override
    else:
        tier = resolve_tier(name, settings=cfg)

    temp = (
        temperature
        if temperature is not None
        else (feature.temperature if feature.temperature is not None else 0.3)
    )
    tokens = max_tokens if max_tokens is not None else feature.max_tokens
    # L-09: HTTP-ретраи внутри модели ограничены budget_ms фичи (не только wait_for снаружи).
    kwargs.setdefault("budget_ms", feature.budget_ms)
    # L-14: effort по фиче (в т.ч. явный None — не откатываться на MODEL_TIER_EFFORT).
    if "reasoning_effort" not in kwargs:
        kwargs["reasoning_effort"] = feature.reasoning_effort

    return get_chat_model(
        tier,
        settings=cfg,
        usage_sink=usage_sink,
        temperature=temp,
        max_tokens=tokens,
        model_override=model_override,
        agent=name,
        **kwargs,
    )


def ensure_features_loaded() -> None:
    """Импортировать `domains/*/llm.py`, чтобы декларации попали в реестр."""
    global _LOADED
    if _LOADED:
        return
    # Импорты побочным эффектом зовут register(...).
    from core.domains.assistant import llm as _assistant_llm  # noqa: F401
    from core.domains.market import llm as _market_llm  # noqa: F401
    from core.domains.multiplayer import llm as _multiplayer_llm  # noqa: F401
    from core.domains.offers import llm as _offers_llm  # noqa: F401
    from core.domains.opportunities import llm as _opportunities_llm  # noqa: F401
    from core.domains.pipeline import llm as _pipeline_llm  # noqa: F401
    from core.domains.preparation import llm as _preparation_llm  # noqa: F401
    from core.domains.profile import llm as _profile_llm  # noqa: F401

    _LOADED = True


def reset_registry_for_tests() -> None:
    """Сброс флага загрузки (только тесты)."""
    global _LOADED
    _LOADED = False


def unregister_for_tests(name: str) -> None:
    """Убрать фичу из реестра (только тесты).

    Временные декларации из тестов иначе утекают в общий реестр и валят контракт A-09
    (`test_llm_features_contract.py`) — он проверяет ВСЕ зарегистрированные фичи.
    """
    _REGISTRY.pop(name, None)


__all__ = [
    "LlmFeature",
    "REASONING_EFFORTS",
    "register",
    "get_feature",
    "require_feature",
    "all_features",
    "resolve_tier",
    "chat_model_for",
    "ensure_features_loaded",
    "reset_registry_for_tests",
    "unregister_for_tests",
]
