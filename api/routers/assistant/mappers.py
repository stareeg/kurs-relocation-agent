"""Проекции разговоров и чата подготовки в транспортные схемы."""

from __future__ import annotations

from collections.abc import Sequence

from api.schemas import (
    AttentionStage,
    AttentionStrongJob,
    ConversationIdentityResult,
    ConversationList,
    ConversationOut,
    HrMessageOut,
    HrThreadOut,
    PrepChatHistory,
    PrepChatMessageOut,
    TodayAttention,
)
from api.schemas.attachments import attachment_meta_out
from core.app.scenarios.conversations import AttentionView, ConversationView
from core.domains.assistant.attachments.models import AttachmentMeta
from core.domains.opportunities.jobs import Job
from core.domains.opportunities.persist import ScoredJob
from core.domains.pipeline.hr_threads import HrMessage, HrThread


def thread_out(thread: HrThread) -> HrThreadOut:
    """Тред в API; `suggestion_source_message_id` внутренний — наружу не светим."""
    data = thread.model_dump()
    data.pop("suggestion_source_message_id", None)
    return HrThreadOut.model_validate(data)


def message_out(message: HrMessage, attachments: Sequence[AttachmentMeta] = ()) -> HrMessageOut:
    return HrMessageOut(
        **message.model_dump(),
        attachments=[attachment_meta_out(a) for a in attachments],
    )


def conversation_out(view: ConversationView) -> ConversationOut:
    return ConversationOut(
        vacancy_id=view.vacancy_id,
        thread=thread_out(view.thread) if view.thread is not None else None,
        messages=[
            message_out(m, view.message_attachments.get(m.id or 0, [])) for m in view.messages
        ],
        hr_link=view.hr_link,
    )


def conversation_identity_out(
    vacancy_id: str, result: ScoredJob | Job
) -> ConversationIdentityResult:
    """Итог карандаша в шапке: `ScoredJob` — пересчитан скор, `Job` — просто сохранены поля."""
    if isinstance(result, ScoredJob):
        return ConversationIdentityResult(
            vacancy_id=vacancy_id,
            company=result.job.company or "",
            title=result.job.title or "",
            scored=True,
            overall_score=result.score.overall_score,
        )
    return ConversationIdentityResult(
        vacancy_id=vacancy_id, company=result.company or "", title=result.title or "", scored=False
    )


def conversation_list(threads) -> ConversationList:
    return ConversationList(items=[thread_out(t) for t in threads])


def attention_out(view: AttentionView) -> TodayAttention:
    return TodayAttention(
        reply=[thread_out(t) for t in view.reply],
        remind=[thread_out(t) for t in view.remind],
        upcoming=[AttentionStage(**s.model_dump()) for s in view.upcoming],
        strong_unapplied=[
            AttentionStrongJob(
                vacancy_id=j.vacancy_id or "",
                title=j.title,
                company=j.company,
                overall_score=j.overall_score,
                scored_at=j.scored_at,
            )
            for j in view.strong_unapplied
        ],
    )


def prep_chat_history(
    vacancy_id: str,
    messages,
    message_attachments: dict[int, list[AttachmentMeta]] | None = None,
) -> PrepChatHistory:
    attachments_map = message_attachments or {}
    return PrepChatHistory(
        vacancy_id=vacancy_id,
        items=[prep_chat_message(m, attachments_map.get(m.id or 0, [])) for m in messages],
    )


def prep_chat_message(message, attachments: Sequence[AttachmentMeta] = ()) -> PrepChatMessageOut:
    return PrepChatMessageOut(
        id=message.id or 0,
        vacancy_id=message.vacancy_id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        reply_to_message_id=message.reply_to_message_id,
        attachments=[attachment_meta_out(a) for a in attachments],
    )


__all__ = [
    "attention_out",
    "conversation_list",
    "conversation_out",
    "message_out",
    "prep_chat_history",
    "prep_chat_message",
    "thread_out",
]
