"""Модели пайплайна HR-переписки: сегментация + результат анализа сообщения.

`HrMessageSegment`/`HrSegmentationResult` — выход LLM-сегментатора
(`core.domains.pipeline.hr_segmenter.segment_hr_messages`): пачка пересланных сообщений →
1–4 смысловых блока с флагами действий (оркестратор делает по ним один проход).

`HrMessageAnalysis` — выход LLM-парсера (`core.domains.pipeline.hr_message_parser`),
вход в `apply_hr_actions`. Этапы — `core.domains.preparation.models`,
время — `core.domains.preparation.interview.timing`.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.preparation.models import InterviewStageIn


def _now_utc() -> datetime:
    return datetime.now(UTC)


# ---- сегментация пачки пересланных сообщений ----

SegmentKind = Literal[
    "rejection",
    "scheduling",
    "hr_questions",
    "outreach",
    "status_update",
    "info",
]

# Действия, которые оркестратор выполняет по сегменту.
SegmentAction = Literal["sheets", "calendar", "reply", "rejection"]


class HrMessageSegment(BaseModel):
    """Один смысловой блок в пачке пересланных сообщений."""

    kind: SegmentKind
    text: str = Field(min_length=1)
    actions: list[SegmentAction] = Field(default_factory=list)
    summary: str = ""


class HrSegmentationResult(BaseModel):
    segments: list[HrMessageSegment] = Field(default_factory=list)
    combined_context: str = ""
    is_self_debrief: bool = False

    @property
    def is_multi(self) -> bool:
        return len(self.segments) > 1

    def kinds_present(self) -> set[SegmentKind]:
        return {s.kind for s in self.segments}

    def has_action(self, action: SegmentAction) -> bool:
        return any(action in s.actions for s in self.segments)


# ---- результат анализа одного HR-сообщения ----

MessageIntent = Literal[
    "interview_scheduled",
    "interview_rescheduled",
    "scheduling_request",
    "rejection",
    "offer",
    "test_task",
    "follow_up",
    "hr_outreach",
    "general",
    "unknown",
]

INTENT_LABELS: dict[str, str] = {
    "interview_scheduled": "Назначено собеседование",
    "interview_rescheduled": "Перенос собеседования",
    "scheduling_request": "HR предлагает выбрать время",
    "rejection": "Отказ",
    "offer": "Оффер",
    "test_task": "Тестовое задание",
    "follow_up": "Продолжение переписки",
    "hr_outreach": "HR написал первым (Telegram)",
    "general": "Общее сообщение",
    "unknown": "Не удалось классифицировать",
}


class HrMessageAnalysis(BaseModel):
    """Результат анализа HR-переписки."""

    intent: MessageIntent = "unknown"
    company: str = "Неизвестная компания"
    position: str = "Неизвестная позиция"
    vacancy_url: str = ""
    vacancy_id: str = ""
    interview_dt: datetime | None = None
    format: Literal["online", "offline", "unknown"] = "unknown"
    interviewer_name: str = ""
    contact: str = ""
    hr_link: str = ""
    salary_text: str = ""
    salary_hr_range: str = ""
    salary_match: Literal["yes", "no", "unclear"] | None = None
    format_clarified: str = ""
    team_size: str = ""
    stage_type: (
        Literal[
            "hr_screening",
            "live_coding",
            "system_design",
            "theory",
            "soft_skills",
            "manager",
            "business_case",
            "final",
        ]
        | None
    ) = None
    interview_stages: list[InterviewStageIn] = Field(default_factory=list)
    source: Literal["hh", "telegram", "email", "other", "habr"] = "telegram"
    funnel_status: str = ""
    summary: str = ""
    debrief_summary: str = ""
    raw_text: str
    parsed_at: datetime = Field(default_factory=_now_utc)
    # Уверенность в привязке vacancy_id (0.0–1.0). Заполняется в resolve_hr_vacancy.
    # < 0.7 → бот не лезет в воронку по vacancy_id и просит пользователя подтвердить.
    resolve_confidence: float = 1.0
    resolve_via: Literal[
        "url_in_text",
        "hr_link_registry",
        "company_search",
        "unresolved",
    ] = "unresolved"

    @property
    def should_update_funnel(self) -> bool:
        if not self.funnel_status:
            return False
        if self.vacancy_id:
            return True
        return self.company not in ("", "Неизвестная компания")

    @property
    def is_inbound(self) -> bool:
        """Нет привязки к hh vacancy_id (cold inbound без ссылки в сообщении)."""
        return not self.vacancy_id

    @property
    def is_cold_hh_outreach(self) -> bool:
        """HR написал по вакансии с hh.ru, которой не было в вашей воронке."""
        return bool(self.vacancy_id) and self.intent in (
            "hr_outreach",
            "follow_up",
            "scheduling_request",
            "general",
            "unknown",
        )

    @property
    def dedup_url_key(self) -> str:
        """Ключ для dedup карточки вакансии по ссылке/company+position."""
        if self.vacancy_url:
            return self.vacancy_url
        if self.vacancy_id:
            return f"https://hh.ru/vacancy/{self.vacancy_id}"
        c = re.sub(r"\W+", "", self.company.lower())[:40]
        p = re.sub(r"\W+", "", self.position.lower())[:40]
        return f"inbound:tg:{c}:{p}"

    @property
    def is_interview_event(self) -> bool:
        return self.intent in ("interview_scheduled", "interview_rescheduled")

    @property
    def is_past_interview(self) -> bool:
        from core.domains.preparation.interview.timing import is_past_datetime

        return self.interview_dt is not None and is_past_datetime(self.interview_dt)
