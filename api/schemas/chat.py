"""Транспортные схемы API: chat."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Задачи оркестратора ---


class ChatStreamRequest(BaseModel):
    """Тело POST /api/chat/stream — бывший payload CreateTask (type=chat)."""

    message: str = ""
    history: list[dict[str, Any]] = Field(default_factory=list)
    vacancy: dict[str, Any] | None = None
    tier: str | None = None
    note_ids: list[int] = Field(default_factory=list)
    resume_gap: bool = False
    hr_draft: bool = False
    # Чат по ситуации на рынке (вкладка «Рынок», внизу под графиками) — карьерный стратег,
    # персист в market_chat_messages. Заменяет бывший блок «Что сделать» (next-steps).
    market: bool = False
    # Чат вкладки «Офферы» (под карточками) — советник по условиям/торгу, персист в
    # offers_chat_messages. Контекст карточек собирается на каждый запрос, не статичный снимок.
    offers: bool = False
    # composer «Ответить»: сообщение-источник, чей текст подставляется цитатой в контекст LLM.
    reply_to_message_id: int | None = None
    # Картинки-вложения текущей реплики (Э2-5, план chat_image_attachments): готовые id из
    # POST /api/attachments — инлайном в модель уходят только они, не вся история (плана).
    attachment_ids: list[int] = Field(default_factory=list)


# --- Q&A по вакансии (чат «Вопросы по вакансии» в расширении) ---


class AskMessage(BaseModel):
    """Реплика диалога Q&A — история чата по вакансии для follow-up."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


# --- Заметки-шпаргалки ---


class NoteCreateRequest(BaseModel):
    """Новая заметка. Пустой заголовок допустим — тело важнее (быстрая шпаргалка на ходу)."""

    title: str = Field(default="", max_length=300)
    body: str = Field(default="", max_length=20_000)
    tags: list[str] = Field(default_factory=list)
    use_in_rag: bool = True


class NoteUpdateRequest(BaseModel):
    """Правка заметки (None = не менять поле)."""

    title: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20_000)
    tags: list[str] | None = None
    use_in_rag: bool | None = None


class NoteMessageCreateRequest(BaseModel):
    """Новое сообщение контекста (UX7: контекст выглядит как чат)."""

    body: str = Field(min_length=1, max_length=20_000)


class NoteMessageUpdateRequest(BaseModel):
    """Правка сообщения контекста (клик по сообщению → редактирование)."""

    body: str = Field(min_length=1, max_length=20_000)


__all__ = [
    "ChatStreamRequest",
    "AskMessage",
    "NoteCreateRequest",
    "NoteUpdateRequest",
    "NoteMessageCreateRequest",
    "NoteMessageUpdateRequest",
]
