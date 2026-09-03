"""LlmSettings — OpenRouter, тиры, прайс, бюджет входа (.env: OPENROUTER_*, MODEL_*)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from core.platform.config.base import normalize_openrouter_model


class LlmSettings(BaseModel):
    """Секреты и инфраструктура LLM. Промпты/тиры фич — в domains/*/llm.py, не здесь."""

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Прокси для split-routing (тот же, что TELEGRAM_PROXY); пусто = прямое соединение.
    openrouter_proxy: str | None = None
    # Глобальный fallback для всех тиров (primary → fallback).
    openrouter_model_fallback: str = ""
    # Тир-осознанный fallback ПЕРЕД глобальным: JSON тир → slug.
    model_tier_fallback: dict[str, str] = {}
    # OpenRouter provider routing (docs: «Provider Routing») — уходит в поле `provider`
    # каждого запроса, если непусто. Пример: {"sort": "throughput"} обходит перегруженный
    # провайдер модели; {"order": ["A", "B"]} фиксирует список. Пусто = решает OpenRouter.
    openrouter_provider: dict[str, Any] = {}

    model_tier_advanced: str = ""
    model_tier_basic: str = ""
    model_tier_reserve: str = ""
    # Раздел «Мультиплеер» — три роли, а не одна модель (Э19.8).
    # `model_multiplayer` — «режиссёр»: мир слота, газета, всё, что про рынок и IT-подоплёку.
    # `model_multiplayer_actor` — «актёр»: прямая речь персонажей (реплики, реакции).
    # `model_multiplayer_arbiter` — «арбитр»: structured-выход, который сверяется с фактами
    #   движка (суд). Единственная роль, где нужен строгий JSON, а не живой текст.
    # Не тир basic/advanced — вызовы с model_override. Пусто у режиссёра = игровые фичи молча
    # отдают статические заглушки; пусто у актёра/арбитра = их роль играет режиссёр.
    model_multiplayer: str = ""
    model_multiplayer_actor: str = ""
    model_multiplayer_arbiter: str = ""
    # Узкие ручные переопределения тира поверх деклараций в domains/*/llm.py.
    agent_tier_overrides: dict[str, str] = {}
    # Легаси: тир → effort только для фабрики модели по сырому тиру (без фичи).
    # Продуктовый путь (chat_model_for / ports.llm) берёт effort из LlmFeature.
    model_tier_effort: dict[str, str] = {}

    # Прайс для cost-учёта (USD за 1M токенов).
    model_prices: dict[str, dict[str, float]] = {}
    default_price_input_per_1m: float = 0.5
    default_price_output_per_1m: float = 1.5

    # Потолок размера одного LLM-запроса (символов); 0 = выключено.
    llm_max_input_chars: int = 800_000
    llm_max_retries: int = 3
    # Пол HTTP к OpenRouter; chat_model_for поднимает до budget_ms фичи + 5с.
    llm_timeout_s: float = 120.0

    def tier_model(self, tier: str) -> str:
        """Имя модели для тира; пусто → пусть падает явной ошибкой в фабрике."""
        raw = {
            "advanced": self.model_tier_advanced,
            "basic": self.model_tier_basic,
            "reserve": self.model_tier_reserve,
        }.get(tier, "")
        return normalize_openrouter_model(raw)

    def multiplayer_model(self) -> str:
        """Slug «режиссёра» раздела: сцена слота и газета (нормализованный)."""
        return normalize_openrouter_model(self.model_multiplayer)

    def multiplayer_actor_model(self) -> str:
        """Slug «актёра» раздела: прямая речь персонажей.

        Пусто → возвращаем режиссёра: одна модель в `.env` должна продолжать работать,
        иначе добавление второй роли ломает уже настроенные установки.
        """
        return normalize_openrouter_model(self.model_multiplayer_actor) or self.multiplayer_model()

    def multiplayer_arbiter_model(self) -> str:
        """Slug «арбитра» раздела: строгий structured-выход. Пусто → режиссёр."""
        return (
            normalize_openrouter_model(self.model_multiplayer_arbiter) or self.multiplayer_model()
        )

    def tier_effort(self, tier: str) -> str | None:
        """OpenRouter reasoning-effort для тира или None, если не задан."""
        return self.model_tier_effort.get(tier) or None

    def tier_fallback(self, tier: str) -> str:
        """Тир-осознанный fallback перед глобальным `openrouter_model_fallback`."""
        return normalize_openrouter_model(self.model_tier_fallback.get(tier, ""))


__all__ = ["LlmSettings"]
