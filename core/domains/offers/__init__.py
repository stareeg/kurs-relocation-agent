"""Домен offers: парсинг, сравнение, торг, бонусы.

Публичный API — ленивый (`__getattr__`).
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "Offer",
    "OfferRecord",
    "compare_offers",
    "load_active_offers",
    "negotiate_offer",
    "parse_offer_text",
    "upsert_offer",
]

_LAZY: dict[str, tuple[str, str]] = {
    "Offer": ("core.domains.offers.store", "Offer"),
    "OfferRecord": ("core.domains.offers.models", "OfferRecord"),
    "compare_offers": ("core.domains.offers.offer_compare", "compare_offers"),
    "load_active_offers": ("core.domains.offers.store", "load_active_offers"),
    "negotiate_offer": ("core.domains.offers.offer_negotiation", "negotiate_offer"),
    "parse_offer_text": ("core.domains.offers.offer_parser", "parse_offer_text"),
    "upsert_offer": ("core.domains.offers.store", "upsert_offer"),
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
