"""Домен pipeline: воронка, HR-переписка, аутрич, сопроводительные.

Публичный API — ленивый (`__getattr__`): иначе цикл
`opportunities.scorer → pipeline.hr_facts → pipeline.__init__ → outreach → opportunities.persist`.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "ActionResult",
    "FunnelSyncResult",
    "apply_hr_actions",
    "attach_vacancy_text",
    "create_outreach_vacancy",
    "funnel_sync",
    "generate_cover_letter",
    "maybe_score_outreach_vacancy",
]

_LAZY: dict[str, tuple[str, str]] = {
    "ActionResult": ("core.domains.pipeline.hr_actions", "ActionResult"),
    "apply_hr_actions": ("core.domains.pipeline.hr_actions", "apply_hr_actions"),
    "FunnelSyncResult": ("core.domains.pipeline.funnel_sync", "FunnelSyncResult"),
    "funnel_sync": ("core.domains.pipeline.funnel_sync", "funnel_sync"),
    "generate_cover_letter": ("core.domains.pipeline.cover_letter", "generate_cover_letter"),
    "create_outreach_vacancy": ("core.domains.pipeline.outreach", "create_outreach_vacancy"),
    "attach_vacancy_text": ("core.domains.pipeline.outreach", "attach_vacancy_text"),
    "maybe_score_outreach_vacancy": (
        "core.domains.pipeline.outreach",
        "maybe_score_outreach_vacancy",
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
