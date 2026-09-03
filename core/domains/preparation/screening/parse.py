"""Общий разбор сырых JSON-ответов LLM для `core/screening/*` - вынесено из `questions.py`, чтобы
не дублировать `_strip_fence` в brief.py/pitch.py/questions.py (план 2026-07-23, шаг 4)."""

from __future__ import annotations


def strip_fence(raw: str) -> str:
    """Снять markdown-обёртку ```json ... ``` вокруг ответа модели, если она есть."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    return raw.strip()


__all__ = ["strip_fence"]
