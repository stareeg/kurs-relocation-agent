"""Доменные модели вложений-картинок.

Одна таблица `attachments` на всю систему — контент-адресуемое хранилище нормализованных байт
(дедуп по sha256). Связки с конкретными лентами (`hr_messages`, `prep_chat_messages`, …) — это
отдельные таблицы (миграции 0091+), эти модели про них ничего не знают.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AttachmentKind = Literal[
    "correspondence", "document", "diagram", "code", "questions", "ui", "photo", "other"
]
AnalysisStatus = Literal["pending", "ready", "failed", "skipped"]

# Ветка вложения в режимах-парсерах (плана, Э4-3): "correspondence" — текст уходит в дамп
# существующего текстового конвейера (hr_import/parse_external), "material" — картинка уходит
# как вложение диалога. Владелец может переопределить угадку классификатора ярлыком-переключателем
# (`RouteBadge`) до отправки — см. `service.resolve_attachment_route`.
AttachmentRoute = Literal["correspondence", "material"]


class AttachmentTurn(BaseModel):
    """Одна реплика на скрине переписки — заполняется только при `kind == "correspondence"`."""

    speaker: str
    text: str


class AttachmentAnalysis(BaseModel):
    """Результат распознавания (`attachment_read`, Этап 1) — jsonb в `attachments.analysis`."""

    kind: AttachmentKind
    title: str
    summary: str
    text: str
    turns: list[AttachmentTurn] = Field(default_factory=list)
    confidence: float = 0.0


class AttachmentMeta(BaseModel):
    """Строка `attachments` без тяжёлых байт (`data`/`thumb`) — мета для API и композера."""

    id: int
    sha256: str
    mime: str
    width: int
    height: int
    bytes: int
    thumb_width: int
    thumb_height: int
    derived_from: int | None = None
    crop: dict | None = None
    analysis_status: AnalysisStatus = "pending"
    analysis: AttachmentAnalysis | None = None
    analyzed_at: datetime | None = None
    created_at: datetime | None = None


class Attachment(AttachmentMeta):
    """Полная строка вместе с байтами — только для отдачи `GET /api/attachments/{id}[/thumb]`."""

    data: bytes
    thumb: bytes


__all__ = [
    "AnalysisStatus",
    "Attachment",
    "AttachmentAnalysis",
    "AttachmentKind",
    "AttachmentMeta",
    "AttachmentRoute",
    "AttachmentTurn",
]
