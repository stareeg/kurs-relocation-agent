"""Хэш входа для сохранённых артефактов, которые не нужно пересобирать без изменений.

Тот же приём, что ключ кэша LLM (`core.platform.llm.call._cache_key`): sha256 конкатенации
частей через `\\0`, усечённый до 32 hex-символов. Здесь — для сравнения с хэшем, сохранённым
рядом с артефактом (скрининг-пакет, prep-pack), а не для ключа кэша.
"""

from __future__ import annotations

import hashlib


def input_digest(*parts: str) -> str:
    """sha256 частей входа → 32 hex-символа. Пустая строка на месте отсутствующей части —
    None недопустим, приводите к строке на стороне вызывающего."""
    joined = "\0".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:32]


__all__ = ["input_digest"]
