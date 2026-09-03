"""Классификация трека вакансии — чистая функция, без LLM.

Условия работы + включённые треки аккаунта → `primary` / `second_job`.
`terms is None` (экстракция не прошла) → primary / low: деградированный путь
не должен угадывать второй трек.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core.domains.opportunities.models import VacancyWorkTerms
from core.kernel.schemas.track import SearchTrack

_CONTRACTOR_ENGAGEMENT = frozenset({"contractor", "b2b", "freelance"})
_PART_SCOPE = frozenset({"part_time", "project"})
_WIDE_GEO = frozenset({"worldwide", "region"})
_SECOND_JOB_HOURS_CAP = 25


@dataclass(frozen=True)
class TrackVerdict:
    track: SearchTrack
    confidence: Literal["high", "medium", "low"]
    reasons: list[str]


def classify_track(
    terms: VacancyWorkTerms | None,
    *,
    profile: object | None = None,
    tracks_enabled: Sequence[SearchTrack],
) -> TrackVerdict:
    """Условия вакансии + набор треков аккаунта → трек карточки.

    `profile` зарезервирован сигнатурой плана (рубрика читает его отдельно);
    классификатору достаточно `terms` и включённых треков.
    """
    _ = profile
    if "second_job" not in tracks_enabled:
        return TrackVerdict(track="primary", confidence="high", reasons=["второй трек выключен"])
    if terms is None:
        return TrackVerdict(
            track="primary",
            confidence="low",
            reasons=["условия работы не извлечены"],
        )

    if terms.engagement in _CONTRACTOR_ENGAGEMENT and terms.scope != "full_time":
        return TrackVerdict(
            track="second_job",
            confidence="high",
            reasons=["контракт/B2B/фриланс не на полный день"],
        )
    if terms.scope in _PART_SCOPE:
        return TrackVerdict(
            track="second_job",
            confidence="high",
            reasons=["part-time или проектная занятость"],
        )
    if terms.weekly_hours is not None and terms.weekly_hours <= _SECOND_JOB_HOURS_CAP:
        return TrackVerdict(
            track="second_job",
            confidence="high",
            reasons=[f"нагрузка {terms.weekly_hours} ч/нед"],
        )
    if terms.engagement in ("contractor", "b2b") and terms.scope == "full_time":
        return TrackVerdict(
            track="primary",
            confidence="medium",
            reasons=["полный контракт заменяет основную работу"],
        )
    currency = (terms.currency or "").strip().upper()
    if (
        currency
        and currency != "RUB"
        and terms.geo_scope in _WIDE_GEO
        and terms.async_culture == "async_first"
    ):
        return TrackVerdict(
            track="second_job",
            confidence="medium",
            reasons=["валюта + широкая география + async-first"],
        )
    return TrackVerdict(
        track="primary",
        confidence="medium",
        reasons=["нет маркеров второго трека"],
    )


__all__ = ["TrackVerdict", "classify_track"]
