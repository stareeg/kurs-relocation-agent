"""Доменные модели career: портфолио, лента, долгая память, дружба.

Без UI. Поля согласованы с ``0070``…``0074_career_facts`` (после чистки Э9.7 —
``0150_drop_career_goals_relocation``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

FriendshipStatus = Literal["active", "blocked"]
TimelineKind = Literal[
    "application",
    "stage",
    "offer",
    "job_start",
    "promotion",
    "project",
    "certificate",
    "relocation",
    "other",
    "search_mode",
    "search_track",
]
FactType = Literal[
    "skill_gap",
    "strength",
    "preference",
    "constraint",
    "company",
    "note",
    "other",
]
FactSourceKind = Literal["vacancy", "debrief", "chat", "manual", "offer", "other"]


class PortfolioItem(BaseModel):
    """Элемент портфолио: проект, роль, результат, артефакт."""

    id: int | None = None
    project: str = Field(min_length=1)
    role: str = ""
    outcome: str = ""
    artifact_url: str = ""
    source_ref: str = ""
    notes: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TimelineEvent(BaseModel):
    """Событие карьерной ленты (отклик, этап, оффер, ручное событие, …)."""

    id: int | None = None
    kind: TimelineKind
    title: str = Field(min_length=1)
    occurred_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_ref: str = ""
    created_at: datetime | None = None


class CareerFact(BaseModel):
    """Долгая память кандидата: факт из разбора/вакансии/чата со сроком годности.

    ``expires_at=None`` — бессрочно; иначе факт выпадает из выборки активных после даты.
    """

    id: int | None = None
    fact: str = Field(min_length=1)
    fact_type: FactType = "note"
    source_kind: FactSourceKind
    source_ref: str = ""
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    recorded_at: datetime | None = None
    expires_at: datetime | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class FriendshipCode(BaseModel):
    """Код дружбы аккаунта: уникальный 6-символьный идентификатор для шаринга."""

    code: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FriendEntry(BaseModel):
    """Друг аккаунта: базовые поля дружбы + публичная информация друга."""

    id: int
    account_id: int
    friend_account_id: int
    friend_name: str = ""
    friend_email: str = ""
    status: FriendshipStatus = "active"
    created_at: datetime | None = None
    origin: str = "user"
    is_admin_peer: bool = False


class FriendProfile(BaseModel):
    """Публичный профиль друга: балл резюме, шанс оффера, имя."""

    account_id: int
    name: str = ""
    resume_score: int | None = None
    offer_chance_pct: float | None = None


__all__ = [
    "CareerFact",
    "FriendEntry",
    "FriendProfile",
    "FriendshipCode",
    "FriendshipStatus",
    "FactSourceKind",
    "FactType",
    "PortfolioItem",
    "TimelineEvent",
    "TimelineKind",
]
