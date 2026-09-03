"""Типизированные идентификаторы доменов.

``NewType`` поверх ``str``/``int``: в рантайме это те же значения (БД/JSON без изменений),
а pyright не даёт подставить ``OfferId`` туда, где нужен ``VacancyId``.

Граница доменов (события, порты, публичные модели) принимает эти типы; сырой ``str``
из репозитория оборачивают конструктором ``VacancyId(raw)`` в момент публикации.
"""

from __future__ import annotations

from typing import NewType

# --- строковые ключи площадок / воронки ---

VacancyId = NewType("VacancyId", str)
ApplicationId = NewType("ApplicationId", str)
OfferId = NewType("OfferId", str)
ConversationId = NewType("ConversationId", str)
InterviewId = NewType("InterviewId", str)
ResumeVersionId = NewType("ResumeVersionId", str)


def vacancy_id(raw: str) -> VacancyId:
    """Обернуть сырой id вакансии (hh / gm_* / …). Пустая строка допустима только как sentinel."""
    return VacancyId(raw)


def offer_id(raw: str) -> OfferId:
    """Обернуть id оффера (в этой системе часто совпадает с vacancy_id)."""
    return OfferId(raw)


def application_id(raw: str) -> ApplicationId:
    return ApplicationId(raw)


def conversation_id(raw: str) -> ConversationId:
    return ConversationId(raw)


def interview_id(raw: str) -> InterviewId:
    return InterviewId(raw)


def resume_version_id(raw: str) -> ResumeVersionId:
    return ResumeVersionId(raw)


def require_vacancy_id(vacancy_id: VacancyId) -> VacancyId:
    """Маркер для typecheck: принимает только VacancyId (см. tests/typecheck)."""
    return vacancy_id


def require_offer_id(offer_id: OfferId) -> OfferId:
    """Маркер для typecheck: принимает только OfferId."""
    return offer_id


__all__ = [
    "ApplicationId",
    "ConversationId",
    "InterviewId",
    "OfferId",
    "ResumeVersionId",
    "VacancyId",
    "application_id",
    "conversation_id",
    "interview_id",
    "offer_id",
    "require_offer_id",
    "require_vacancy_id",
    "resume_version_id",
    "vacancy_id",
]
