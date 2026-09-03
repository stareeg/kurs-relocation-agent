"""Транспортные схемы API: career (режим поиска, трек, портфолио, дружба).

Доменные модели (`PortfolioItem`, `TimelineEvent`) переиспользуются из
`core.domains.career.models` как response-схемы напрямую — здесь только запросы
(Create/Patch) и составные ответы, которых у домена нет.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.domains.career.models import TimelineEvent
from core.domains.career.search_state import SearchMode, SearchModeActor
from core.domains.career.track_state import SearchTrackActor

#: Виды событий, которые владелец заводит руками — единственное ручное действие всего экрана
#: «Карьера» (Э9.3). Системные виды (application/stage/offer/search_mode/search_track) пишутся
#: только подписчиками событий (career/events.py), не этой ручкой. Фронт (`TimelineFeed.tsx`,
#: `plans/career_redesign_2026_08_26.md`) не даёт выбрать "other" — техническое «другое», не
#: осмысленный выбор человека — но тип оставлен шире, чем UI, на случай программного клиента.
ManualTimelineKind = Literal[
    "job_start", "promotion", "project", "certificate", "relocation", "other"
]


class SearchModeOut(BaseModel):
    """Текущий режим поиска: машинное значение + человеческая подпись для UI."""

    mode: SearchMode
    label: str = Field(min_length=1)
    since: datetime | None = None


class SearchModePatch(BaseModel):
    """Переключение режима. `actor="suggestion"` — владелец принял предложение системы;
    сама система режим не переключает."""

    mode: SearchMode
    actor: SearchModeActor = "owner"
    reason: str = ""


class SearchTrackOut(BaseModel):
    """Текущий набор треков поиска: основная всегда включена, вторая — тумблер."""

    tracks: list[str]
    labels: list[str]
    second_job_enabled: bool
    since: datetime | None = None


class SearchTrackPatch(BaseModel):
    """Включить/выключить вторую работу. Основной трек этой ручкой не выключается."""

    second_job_enabled: bool
    actor: SearchTrackActor = "owner"
    reason: str = ""


class TimelineEventCreate(BaseModel):
    """Ручное событие ленты: «вышел на работу», «получил сертификат» и т.п. (Э9.3)."""

    kind: ManualTimelineKind
    title: str = Field(min_length=1)
    occurred_at: datetime | None = None


class TimelineEventView(TimelineEvent):
    """`TimelineEvent` + обогащение на чтении (Этап 2 плана редизайна «Карьеры»,
    `core/app/scenarios/career_timeline_view.py`). Пустые `company`/`vacancy_title` — вакансия
    не резолвится, фронт показывает `title` как есть (там уже сырой id — старое поведение)."""

    company: str = ""
    vacancy_title: str = ""
    href: str | None = None


class CareerFactPatch(BaseModel):
    """Правка факта долгой памяти: текст и/или закрепление (Э9.4).

    `pinned=True` снимает срок годности (бессрочно); отсутствие поля/`False` срок не трогает —
    снять закрепление этой ручкой нельзя (см. `core.domains.career.repo.update_fact`)."""

    fact: str | None = Field(default=None, min_length=1)
    pinned: bool | None = None


class PortfolioItemCreate(BaseModel):
    """Элемент портфолио, добавленный вручную."""

    project: str = Field(min_length=1)
    role: str = ""
    outcome: str = ""
    artifact_url: str = ""
    source_ref: str = ""
    notes: str = ""


class PortfolioDraftFromDebriefRequest(BaseModel):
    """Черновик портфолио из разбора собеса — поля берутся с уже открытого разбора на фронте."""

    vacancy_id: str = ""
    company: str = ""
    strong_answers: list[str] = Field(default_factory=list)
    summary: str = ""
    debrief_id: int | None = None


class PortfolioDraftFromOfferRequest(BaseModel):
    """Черновик портфолио из оффера/торга — поля берутся с уже открытого оффера на фронте."""

    vacancy_id: str = Field(min_length=1)
    company: str = ""
    position: str = ""
    base_salary: int | None = None
    base_salary_currency: str = "RUB"
    negotiation_points: list[str] = Field(default_factory=list)


class FriendshipCodeOut(BaseModel):
    """Код дружбы аккаунта для шаринга."""

    code: str


class AddFriendRequest(BaseModel):
    """Добавить друга по коду дружбы."""

    code: str = Field(min_length=1)


__all__ = [
    "AddFriendRequest",
    "CareerFactPatch",
    "FriendshipCodeOut",
    "ManualTimelineKind",
    "PortfolioDraftFromDebriefRequest",
    "PortfolioDraftFromOfferRequest",
    "PortfolioItemCreate",
    "SearchModeOut",
    "SearchModePatch",
    "SearchTrackOut",
    "SearchTrackPatch",
    "TimelineEventCreate",
    "TimelineEventView",
]
