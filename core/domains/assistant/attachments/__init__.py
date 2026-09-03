"""Вложения-картинки в чатах.

`models` — доменные типы, `repo` — доступ к таблице `attachments`, `service` — сценарии верхнего
уровня (`store_upload`/`get_meta`/`crop_attachment`) с обязательным персистом (нет PG → 503).
"""

from __future__ import annotations

from core.domains.assistant.attachments.models import (
    AnalysisStatus,
    Attachment,
    AttachmentAnalysis,
    AttachmentKind,
    AttachmentMeta,
    AttachmentTurn,
)
from core.domains.assistant.attachments.service import (
    crop_attachment,
    get_attachment,
    get_meta,
    store_upload,
)

__all__ = [
    "AnalysisStatus",
    "Attachment",
    "AttachmentAnalysis",
    "AttachmentKind",
    "AttachmentMeta",
    "AttachmentTurn",
    "crop_attachment",
    "get_attachment",
    "get_meta",
    "store_upload",
]
