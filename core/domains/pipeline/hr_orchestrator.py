"""Оркестрация HR-пачки: parse + флаги сегментов + apply_hr_actions.

Без бота и без prep-reminders: пинги планирования — ответственность канала
(`bot_app.services.prep_scheduler` после вызова).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from core.domains.pipeline.events import publish_hr_message_received
from core.domains.pipeline.hr_actions import ActionResult, apply_hr_actions
from core.domains.pipeline.hr_context import enrich_analysis_from_text
from core.domains.pipeline.hr_message_parser import parse_hr_message
from core.domains.pipeline.hr_segmenter import segment_hr_messages
from core.domains.pipeline.models import (
    HrMessageAnalysis,
    HrMessageSegment,
    HrSegmentationResult,
)
from core.kernel.schemas.funnel import FunnelStatus

logger = logging.getLogger(__name__)


@dataclass
class HrBatchResult:
    """Итог обработки пачки HR-сообщений."""

    primary: HrMessageAnalysis
    actions: ActionResult = field(default_factory=ActionResult)


def _apply_segment_flags(
    primary: HrMessageAnalysis, segmentation: HrSegmentationResult
) -> HrMessageAnalysis:
    """Сегменты только для флага rejection, не для N× LLM."""
    merged = primary

    if segmentation.has_action("rejection") or any(
        s.kind == "rejection" for s in segmentation.segments
    ):
        merged = merged.model_copy(
            update={
                "intent": "rejection",
                "funnel_status": FunnelStatus.REJECTED,
            }
        )

    return enrich_analysis_from_text(merged)


async def process_hr_batch(text: str, telegram_msg_id: int, *, account_id: int) -> HrBatchResult:
    """1) parse всей пачки 2) segmenter (только флаги) 3) apply_hr_actions."""
    full_text = text.strip()
    segmentation = await segment_hr_messages(full_text)
    primary = await parse_hr_message(full_text)

    if not segmentation.segments:
        segmentation = HrSegmentationResult(
            segments=[
                HrMessageSegment(
                    kind="outreach",
                    text=full_text,
                    actions=["sheets"],
                    summary=primary.summary,
                )
            ],
            combined_context=full_text,
        )

    merged = _apply_segment_flags(primary, segmentation)
    merged = merged.model_copy(update={"raw_text": full_text})

    actions = await apply_hr_actions(merged, telegram_msg_id, account_id=account_id)

    # A-11: переписка разобрана и применена — дальше это событие, а не звонок в чужой домен.
    publish_hr_message_received(
        vacancy_id=merged.vacancy_id,
        intent=str(merged.intent or ""),
        funnel_status=actions.funnel_status or str(merged.funnel_status or ""),
        channel=str(merged.source or ""),
        account_id=account_id,
    )
    return HrBatchResult(primary=merged, actions=actions)


__all__ = ["HrBatchResult", "process_hr_batch"]
