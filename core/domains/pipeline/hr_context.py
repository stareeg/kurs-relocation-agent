"""Дополнение HR-разбора эвристиками (компания, дата собеса из заметок) — порт S11."""

from __future__ import annotations

import contextlib
from datetime import datetime

from core.domains.pipeline.heuristic_hr import heuristic_extract
from core.domains.pipeline.models import HrMessageAnalysis


def enrich_analysis_from_text(analysis: HrMessageAnalysis) -> HrMessageAnalysis:
    """Заполнить пустые поля из полного текста / заметок пользователя."""
    h = heuristic_extract(analysis.raw_text)
    if not h:
        return analysis

    updates: dict = {}

    if analysis.company in ("", "Неизвестная компания") and h.get("company"):
        updates["company"] = h["company"]

    if analysis.position in ("", "Неизвестная позиция") and h.get("position"):
        updates["position"] = h["position"]

    if not analysis.interview_dt and h.get("interview_dt"):
        with contextlib.suppress(TypeError, ValueError):
            updates["interview_dt"] = datetime.fromisoformat(h["interview_dt"])

    if h.get("intent") == "rejection" and analysis.intent in ("unknown", "general"):
        updates["intent"] = "rejection"
        updates["funnel_status"] = h.get("funnel_status", analysis.funnel_status)

    if h.get("stage_type") and not analysis.stage_type:
        updates["stage_type"] = h["stage_type"]

    if not updates:
        return analysis
    return analysis.model_copy(update=updates)
