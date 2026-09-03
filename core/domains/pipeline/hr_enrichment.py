"""Постобработка enrichment и этапов из HR-сообщения (порт `bot.services.hr_enrichment`, S11).

Таксономия этапов переехала в `core.domains.preparation.models`; здесь — эвристика типа этапа по тексту
и нормализация LLM-полей (interview_stages, salary_match).
"""

from __future__ import annotations

import re
from typing import Literal

from core.domains.preparation.models import (
    STAGE_TO_FUNNEL_STATUS,
    InterviewStageIn,
    InterviewStageType,
)

_VALID_STAGE_TYPES = {
    "hr_screening",
    "live_coding",
    "system_design",
    "theory",
    "soft_skills",
    "manager",
    "final",
    "business_case",
}


def is_valid_stage_type(value: str) -> bool:
    return value in _VALID_STAGE_TYPES


def infer_stage_type(text: str, parsed: dict) -> InterviewStageType:
    raw = (parsed.get("stage_type") or "").strip()
    if raw in _VALID_STAGE_TYPES:
        return raw  # type: ignore[return-value]

    lower = text.lower()
    if re.search(r"финал|final\s*round|с\s+(руководител|ceo|cto|head\s+of)|онсайт|onsite", lower):
        return "final"
    if re.search(r"live\s*coding|кодинг|leetcode|algo", lower):
        return "live_coding"
    if re.search(r"system\s*design|архитектур", lower):
        return "system_design"
    if re.search(r"\bтеор", lower):
        return "theory"
    if re.search(r"менедж|руковод|director|head of", lower):
        return "manager"
    if re.search(r"soft\s*skill|культур|fit", lower):
        return "soft_skills"
    if re.search(r"технич|technical|инженер", lower):
        return "live_coding"
    if re.search(r"скрининг|screening|знакомств", lower):
        return "hr_screening"
    return "hr_screening"


def funnel_status_for_stage(stage_type: InterviewStageType) -> str:
    return STAGE_TO_FUNNEL_STATUS.get(stage_type, STAGE_TO_FUNNEL_STATUS["hr_screening"])


def parse_interview_stages(parsed: dict) -> list[InterviewStageIn]:
    raw = parsed.get("interview_stages") or []
    if not isinstance(raw, list):
        return []

    stages: list[InterviewStageIn] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        stage_type = item.get("stage_type") or "hr_screening"
        if stage_type not in _VALID_STAGE_TYPES:
            continue
        scheduled_at = None
        if item.get("scheduled_at"):
            try:
                from datetime import datetime

                scheduled_at = datetime.fromisoformat(str(item["scheduled_at"]))
            except Exception:
                scheduled_at = None
        fmt = item.get("format", "unknown")
        if fmt not in ("online", "offline", "unknown"):
            fmt = "unknown"
        status = item.get("status", "scheduled")
        if status not in ("scheduled", "completed", "cancelled", "rescheduled"):
            status = "scheduled"
        stages.append(
            InterviewStageIn(
                stage_type=stage_type,
                scheduled_at=scheduled_at,
                format=fmt,
                status=status,
                notes=str(item.get("notes") or ""),
            )
        )
    return stages


def parse_salary_match(value: object) -> Literal["yes", "no", "unclear"] | None:
    if value is None or value == "":
        return None
    text = str(value).lower().strip()
    if text in ("yes", "да", "true"):
        return "yes"
    if text in ("no", "нет", "false"):
        return "no"
    return "unclear"
