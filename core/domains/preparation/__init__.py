"""Домен preparation: скрининг, технички, разбор, легенда.

Публичный API — ленивый (`__getattr__`), чтобы не тянуть LLM/PG при импорте пакета.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "VacancySelfPres",
    "analyze_debrief",
    "ask_about_vacancy",
    "generate_prep_questions",
    "generate_self_pres_pack",
    "load_self_pres_context",
    "record_from_request_fallback",
]

_LAZY: dict[str, tuple[str, str]] = {
    "VacancySelfPres": ("core.domains.preparation.screening", "VacancySelfPres"),
    "generate_self_pres_pack": (
        "core.domains.preparation.screening",
        "generate_self_pres_pack",
    ),
    "load_self_pres_context": (
        "core.domains.preparation.screening",
        "load_self_pres_context",
    ),
    "analyze_debrief": ("core.domains.preparation.interview", "analyze_debrief"),
    "generate_prep_questions": (
        "core.domains.preparation.interview",
        "generate_prep_questions",
    ),
    "ask_about_vacancy": ("core.domains.preparation.asker", "ask_about_vacancy"),
    "record_from_request_fallback": (
        "core.domains.preparation.asker",
        "record_from_request_fallback",
    ),
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
