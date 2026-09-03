"""Домен assistant: прямой стрим чата, заметки, prep-чат.

Публичный API — ленивый (`__getattr__`).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AskMessage",
    "CHAT_AGENT",
    "Note",
    "stream_answer",
]

_LAZY: dict[str, tuple[str, str]] = {
    "AskMessage": ("core.domains.assistant.models", "AskMessage"),
    "CHAT_AGENT": ("core.domains.assistant.service", "CHAT_AGENT"),
    "Note": ("core.domains.assistant.notes", "Note"),
    "stream_answer": ("core.domains.assistant.service", "stream_answer"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod_name, attr = target
    import importlib

    mod = importlib.import_module(mod_name)
    value = getattr(mod, attr)
    globals()[name] = value
    return value
