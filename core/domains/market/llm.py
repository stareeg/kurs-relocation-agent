"""LLM-фичи домена market (реестр LlmFeature — A-06/A-09)."""

from __future__ import annotations

from core.platform.llm.registry import LlmFeature, register

SITUATION = "prompts/market/situation.md"
MARKET_CHAT = "prompts/market/chat.md"

SITUATION_FEAT = register(
    LlmFeature(
        name="situation",
        tier="advanced",
        prompt=SITUATION,
        temperature=0.4,
        cache_prefix=True,
        max_tokens=8192,
        budget_ms=120_000,
        retries=1,
        reasoning_effort="medium",  # L-14: аналитика рынка
        # schema динамическая (несколько параллельных кусков) — передаётся в run().
    )
)
# Чат по ситуации на рынке (вкладка «Рынок», внизу под графиками) — диалоговый стримовый
# режим в `/api/chat/stream` (флаг `market: true`), замена бывшего блока «Что сделать».
# reasoning-тир: аналитика рынка требует взвешенных выводов; medium-эффорт не нужен (вопросы
# чаще прямые, не нужны длинные рассуждения с цепочкой). cache_prefix — static system +
# dynamic_tail facts (как qa_vacancy/resume_gap).
MARKET_CHAT_FEAT = register(
    LlmFeature(
        name="market_chat",
        tier="advanced",
        prompt=MARKET_CHAT,
        temperature=0.4,
        cache_prefix=True,
        max_tokens=4096,
        budget_ms=90_000,
        retries=1,
    )
)
SALARY_EXTRACT = register(
    LlmFeature(
        name="salary_extract",
        tier="basic",
        max_tokens=1024,
        budget_ms=20_000,
        retries=1,
        prompt_in_code=True,
    )
)

FEATURES: tuple[LlmFeature, ...] = (SITUATION_FEAT, MARKET_CHAT_FEAT, SALARY_EXTRACT)

PROMPT_PATHS: dict[str, str] = {
    "situation": SITUATION,
    "market_chat": MARKET_CHAT,
}

__all__ = [
    "FEATURES",
    "MARKET_CHAT",
    "MARKET_CHAT_FEAT",
    "SITUATION",
    "SITUATION_FEAT",
    "SALARY_EXTRACT",
    "PROMPT_PATHS",
]
