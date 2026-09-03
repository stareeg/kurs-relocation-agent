"""Транспортная схема аватара владельца (`/api/profile/avatar`).

Байты отдельно от меты (`GET /api/profile/avatar` без `/meta` — сразу картинка, как
`/api/attachments/{id}`) — мета нужна фронту только чтобы решить, показывать ли `<img>`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.domains.profile.avatar import AvatarSource


class AvatarMetaOut(BaseModel):
    source: AvatarSource
    width: int
    height: int
    updated_at: datetime


__all__ = ["AvatarMetaOut"]
