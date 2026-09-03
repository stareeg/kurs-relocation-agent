"""Домен market: рынок, пульс, сетка, ситуация, калибровка зарплат.

Публичный API — ленивый (`__getattr__`).
Funnel-аналитика — в `core.domains.pipeline.analytics` / `source_funnel`.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "MarketGrid",
    "MarketPulse",
    "SituationNarrative",
    "generate_situation_narrative",
    "get_market_grid",
    "get_market_pulse",
]

_LAZY: dict[str, tuple[str, str]] = {
    "MarketGrid": ("core.domains.market.market_grid", "MarketGrid"),
    "MarketPulse": ("core.domains.market.pulse", "MarketPulse"),
    "SituationNarrative": ("core.domains.market.situation", "SituationNarrative"),
    "generate_situation_narrative": (
        "core.domains.market.situation",
        "generate_situation_narrative",
    ),
    "get_market_grid": ("core.domains.market.market_grid", "get_market_grid"),
    "get_market_pulse": ("core.domains.market.pulse", "get_market_pulse"),
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
