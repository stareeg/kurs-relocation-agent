"""Доменные модели assistant: реплики чата / Q&A.

`AskMessage` — история для vacancy Q&A (`preparation.asker`) и расширения.
HTTP-контракты стрима — в `api.schemas` (`ChatStreamRequest`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AskRole = Literal["user", "assistant"]


class AskMessage(BaseModel):
    role: AskRole
    content: str = Field(min_length=1, max_length=4000)


__all__ = ["AskMessage", "AskRole"]
