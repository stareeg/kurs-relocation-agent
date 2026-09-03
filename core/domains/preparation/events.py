"""События домена preparation: что публикует и на что подписан (шина — A-11)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from core.kernel import ports
from core.kernel.events import ApplicationStageChanged, InterviewDebriefed, ScreeningPackReady
from core.kernel.ids import VacancyId
from core.kernel.schemas.funnel import FunnelStatus

logger = logging.getLogger(__name__)

PUBLISHES: tuple[type, ...] = (ScreeningPackReady, InterviewDebriefed)


#: Стадии, до которых нельзя доехать, не пройдя скрининг. Раньше тут была одна «Техничка», и
#: вакансия, прыгнувшая из «Скрининга» сразу в «Финал»/«Оффер» (частый случай: HR зовёт на
#: финал), оставалась без строки скрининга в цепочке.
_STAGES_AFTER_SCREENING = frozenset(
    {FunnelStatus.TECH.value, FunnelStatus.FINAL.value, FunnelStatus.OFFER.value}
)


async def on_application_stage_changed(evt: ApplicationStageChanged) -> None:
    """Переход в «Скрининг» ⇒ строка HR-скрининга должна появиться в цепочке открытой; переход в
    «Техничку» и дальше ⇒ HR-скрининг уже позади — гасим его кружок.

    Раньше это делал сам `opportunities.add_stage` ленивым импортом preparation — прямой вызов
    чужого домена ради побочного эффекта. Теперь эффект живёт у того, кому принадлежит.
    """
    if not evt.vacancy_id or not evt.account_id:
        return

    if evt.stage == FunnelStatus.SCREENING.value:
        from core.domains.preparation.interview_stages import ensure_hr_screening_stage_open

        await ensure_hr_screening_stage_open(evt.vacancy_id, account_id=evt.account_id)
        return

    if evt.stage in _STAGES_AFTER_SCREENING:
        from core.domains.preparation.interview_stages import ensure_hr_screening_completed

        await ensure_hr_screening_completed(evt.vacancy_id, account_id=evt.account_id)


SUBSCRIPTIONS: tuple[tuple[type, Callable[[Any], Any]], ...] = (
    (ApplicationStageChanged, on_application_stage_changed),
)
SUBSCRIBES: tuple[type, ...] = tuple(t for t, _ in SUBSCRIPTIONS)


def publish_screening_pack_ready(
    *,
    vacancy_id: str,
    company: str = "",
    pitch_blocks: int = 0,
    hr_questions: int = 0,
) -> None:
    """Пакет самопрезентации собран (в т.ч. частично — деградация пакета это норма)."""
    if not vacancy_id:
        return
    ports.events().publish(
        ScreeningPackReady(
            vacancy_id=VacancyId(vacancy_id),
            company=company,
            pitch_blocks=pitch_blocks,
            hr_questions=hr_questions,
        )
    )


def publish_interview_debriefed(
    *,
    vacancy_id: str,
    account_id: int,
    stage: str = "",
    signal: str = "",
    debrief_id: int | None = None,
) -> None:
    """Разбор собеседования сохранён."""
    ports.events().publish(
        InterviewDebriefed(
            vacancy_id=VacancyId(vacancy_id),
            stage=stage,
            signal=signal,
            debrief_id=debrief_id,
            account_id=account_id,
        )
    )


__all__ = [
    "PUBLISHES",
    "SUBSCRIBES",
    "SUBSCRIPTIONS",
    "InterviewDebriefed",
    "ScreeningPackReady",
    "on_application_stage_changed",
    "publish_interview_debriefed",
    "publish_screening_pack_ready",
]
