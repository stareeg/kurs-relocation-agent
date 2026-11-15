"""Загрузка системных промптов агента из `prompts/agent/` (A-1).

Промпты живут отдельными файлами рядом с кодом (PLAN, таблица модулей), читаются один раз
и кэшируются: граф собирается на каждый запуск, но содержимое файлов не меняется.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Системный промпт узла агента из `prompts/agent/<name>.md`."""
    path = _ROOT / "prompts" / "agent" / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"промпт агента не найден: {path}")
    return path.read_text(encoding="utf-8")


__all__ = ["load_prompt"]
