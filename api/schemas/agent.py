"""Контракты агента: запуски, события, чат-сессии (A-3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRunCreate(BaseModel):
    """Запуск агента фоновой задачей; `session_id` привязывает запуск к диалогу чата."""

    goal: str = Field(min_length=1, max_length=4000)
    session_id: int | None = None


class AgentRunOut(BaseModel):
    """Строка запуска: статус, итог, ошибка. thread_id наружу не отдаём."""

    id: int
    goal: str
    status: str
    session_id: int | None = None
    stop_reason: str | None = None
    answer: str | None = None
    error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # Расход запуска (E-9): вызовы модели, токены, цена, разбивка и пределы; {} — нет данных.
    usage: dict[str, Any] = Field(default_factory=dict)


class AgentRunList(BaseModel):
    items: list[AgentRunOut]


class AgentApprovalEdits(BaseModel):
    """Правка карточки перед «да» (U-1): текст для работодателя, пределы — как у `queue_application`."""

    cover_note: str | None = Field(default=None, min_length=40, max_length=600)


class AgentApprovalIn(BaseModel):
    """Решение человека по карточке действия: «да» выполняет действие, «нет» отклоняет.

    `edits` — «да» с правкой: узел `confirm` подставит текст человека вместо текста агента.
    """

    approved: bool
    edits: AgentApprovalEdits | None = None


class AgentSettingsOut(BaseModel):
    """Настройки агента аккаунта: режим подтверждения действий (OQ-8)."""

    confirm_mode: Literal["ask", "auto"]


class AgentSettingsIn(BaseModel):
    confirm_mode: Literal["ask", "auto"]


class AgentEventOut(BaseModel):
    """Событие запуска: тип + payload, узел и время узла (таймеры, OQ-29)."""

    id: int
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    node: str | None = None
    duration_ms: float | None = None
    created_at: datetime | None = None


class AgentEventList(BaseModel):
    items: list[AgentEventOut]


class AgentChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class AgentChatSessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class AgentChatSessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentChatSessionList(BaseModel):
    items: list[AgentChatSessionOut]


class AgentChatMessageIn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=20000)


class AgentChatMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    created_at: datetime | None = None


class AgentChatMessageList(BaseModel):
    items: list[AgentChatMessageOut]
