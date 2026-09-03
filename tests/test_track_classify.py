"""Э2.2: табличные правила classify_track."""

from __future__ import annotations

import pytest

from core.domains.opportunities.models import VacancyWorkTerms
from core.domains.opportunities.track_classify import classify_track


def test_second_track_off_is_primary_high() -> None:
    terms = VacancyWorkTerms(engagement="contractor", scope="part_time")
    v = classify_track(terms, tracks_enabled=["primary"])
    assert v.track == "primary"
    assert v.confidence == "high"


def test_terms_none_is_primary_low() -> None:
    v = classify_track(None, tracks_enabled=["primary", "second_job"])
    assert v.track == "primary"
    assert v.confidence == "low"


@pytest.mark.parametrize(
    ("terms", "track", "confidence"),
    [
        (
            VacancyWorkTerms(engagement="contractor", scope="part_time"),
            "second_job",
            "high",
        ),
        (
            VacancyWorkTerms(engagement="b2b", scope="project"),
            "second_job",
            "high",
        ),
        (
            VacancyWorkTerms(engagement="freelance", scope="unknown"),
            "second_job",
            "high",
        ),
        (VacancyWorkTerms(scope="part_time"), "second_job", "high"),
        (VacancyWorkTerms(scope="project"), "second_job", "high"),
        (VacancyWorkTerms(weekly_hours=20), "second_job", "high"),
        (
            VacancyWorkTerms(engagement="contractor", scope="full_time"),
            "primary",
            "medium",
        ),
        (
            VacancyWorkTerms(
                currency="USD", geo_scope="worldwide", async_culture="async_first"
            ),
            "second_job",
            "medium",
        ),
        (VacancyWorkTerms(), "primary", "medium"),
    ],
)
def test_classify_track_table(terms: VacancyWorkTerms, track: str, confidence: str) -> None:
    v = classify_track(terms, tracks_enabled=["primary", "second_job"])
    assert v.track == track
    assert v.confidence == confidence
