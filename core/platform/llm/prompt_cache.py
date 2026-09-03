"""Prompt caching helper (задача 0.2, подшаг 4).

Разделяет системный промпт на статичный префикс (роль + резюме + instructions) и
динамический хвост. Статичный кусок помечается `cache_control: ephemeral` —
OpenRouter кэширует его для поддерживающих провайдеров (anthropic/deepseek/...).
Для моделей без поддержки cache_control блоки схлопываются в обычный текст в
конвертере сообщений (см. openrouter_chat._render_content), так что промпт не ломается.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import SystemMessage

# Семейства, которым OpenRouter прокидывает Anthropic-style cache_control.
# Для остальных (gemini и т.п.) кэш у провайдера неявный — маркер не нужен и его
# срезаем при рендере, чтобы не словить 400.
_CACHE_CONTROL_FAMILIES = ("anthropic/", "deepseek/")


def supports_cache_control(model: str) -> bool:
    m = model.lower()
    return "claude" in m or any(m.startswith(f) for f in _CACHE_CONTROL_FAMILIES)


def build_cached_system_prompt(
    static_prefix: str,
    dynamic_tail: str = "",
    *,
    cache: bool = True,
) -> SystemMessage:
    """SystemMessage со статичным префиксом, помеченным под кэш, и динамическим хвостом.

    cache=False → обычный текстовый SystemMessage (склейка префикса и хвоста).
    """
    static_prefix = (static_prefix or "").strip()
    dynamic_tail = (dynamic_tail or "").strip()

    if not cache:
        text = static_prefix
        if dynamic_tail:
            text = f"{text}\n\n{dynamic_tail}" if text else dynamic_tail
        return SystemMessage(content=text)

    blocks: list[str | dict[Any, Any]] = [
        {"type": "text", "text": static_prefix, "cache_control": {"type": "ephemeral"}}
    ]
    if dynamic_tail:
        blocks.append({"type": "text", "text": dynamic_tail})
    return SystemMessage(content=blocks)
