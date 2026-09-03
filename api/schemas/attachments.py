"""Транспортные схемы вложений-картинок (`/api/attachments`, Э0-4).

`AttachmentOut` — то, что видит фронт: мета `AttachmentMeta` плюс готовые `url`/`thumb_url`
(роутер сам знает свой префикс, фронту не нужно его собирать).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.domains.assistant.attachments.models import (
    AnalysisStatus,
    AttachmentAnalysis,
    AttachmentMeta,
)


class AttachmentOut(BaseModel):
    id: int
    mime: str
    width: int
    height: int
    bytes: int
    thumb_width: int
    thumb_height: int
    url: str
    thumb_url: str
    derived_from: int | None = None
    crop: dict | None = None
    analysis_status: AnalysisStatus = "pending"
    analysis: AttachmentAnalysis | None = None
    created_at: datetime | None = None


class AttachmentCropRequest(BaseModel):
    """Доли 0..1 относительно исходной картинки (см. `core.platform.images.crop`)."""

    x: float
    y: float
    w: float
    h: float


def attachment_meta_out(meta: AttachmentMeta) -> AttachmentOut:
    """`AttachmentMeta` → транспортная схема с готовыми `url`/`thumb_url`.

    Общая точка правды для роутера `/api/attachments` и для проекции вложений сообщений
    (`api/routers/assistant/mappers.py`, Э2-5) — фронту не нужно самому собирать путь.
    """
    return AttachmentOut(
        id=meta.id,
        mime=meta.mime,
        width=meta.width,
        height=meta.height,
        bytes=meta.bytes,
        thumb_width=meta.thumb_width,
        thumb_height=meta.thumb_height,
        url=f"/api/attachments/{meta.id}",
        thumb_url=f"/api/attachments/{meta.id}/thumb",
        derived_from=meta.derived_from,
        crop=meta.crop,
        analysis_status=meta.analysis_status,
        analysis=meta.analysis,
        created_at=meta.created_at,
    )


__all__ = ["AttachmentCropRequest", "AttachmentOut", "attachment_meta_out"]
