"""LLM-фичи домена offers (реестр LlmFeature — A-06/A-09)."""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

BONUS_ESTIMATE = "prompts/offers/bonus_estimate.md"
OFFERS_CHAT = "prompts/offers/chat.md"

OFFER_PARSE = register(
    LlmFeature(
        name="offer_parse",
        tier="basic",
        max_tokens=2048,
        budget_ms=30_000,
        retries=1,
        prompt_in_code=True,
        cache_prefix=True,  # L-11
    )
)
OFFER_COMPARE = register(
    LlmFeature(
        name="offer_compare",
        tier="basic",
        max_tokens=4096,
        budget_ms=45_000,
        retries=1,
        prompt_in_code=True,
        cache_prefix=True,  # L-11: резюме+правила статичны, офферы в user
    )
)
OFFER_NEGOTIATION = register(
    LlmFeature(
        name="offer_negotiation",
        tier="advanced",
        max_tokens=4096,
        budget_ms=75_000,
        retries=1,
        reasoning_effort="medium",  # L-14
        prompt_in_code=True,
        cache_prefix=True,  # L-11: правила/стиль в prefix, оффер — dynamic_tail
    )
)
OFFER_BONUS_ESTIMATE = register(
    LlmFeature(
        name="offer_bonus_estimate",
        tier="basic",
        prompt=BONUS_ESTIMATE,
        cache_prefix=True,  # L-11
        temperature=0.1,
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
    )
)
# Чат вкладки «Офферы» — стримовый режим `/api/chat/stream` (флаг `offers: true`).
# cache_prefix: статичный system + dynamic_tail со свежим снимком карточек.
OFFERS_CHAT_FEAT = register(
    LlmFeature(
        name="offers_chat",
        tier="advanced",
        prompt=OFFERS_CHAT,
        temperature=0.4,
        cache_prefix=True,
        max_tokens=4096,
        budget_ms=90_000,
        retries=1,
    )
)

FEATURES: tuple[LlmFeature, ...] = (
    OFFER_PARSE,
    OFFER_COMPARE,
    OFFER_NEGOTIATION,
    OFFER_BONUS_ESTIMATE,
    OFFERS_CHAT_FEAT,
)

PROMPT_PATHS: dict[str, str] = {
    "bonus_estimate": BONUS_ESTIMATE,
    "offers_chat": OFFERS_CHAT,
}

__all__ = [
    "FEATURES",
    "BONUS_ESTIMATE",
    "OFFERS_CHAT",
    "OFFER_PARSE",
    "OFFER_COMPARE",
    "OFFER_NEGOTIATION",
    "OFFER_BONUS_ESTIMATE",
    "OFFERS_CHAT_FEAT",
    "PROMPT_PATHS",
]
