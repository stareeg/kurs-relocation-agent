"""Unit-тесты: пустые stub-вакансии без скора — признак «нужен текст» и TTL-purge."""

from __future__ import annotations

from core.domains.opportunities.jobs import (
    EMPTY_UNSCORED_TTL_HOURS,
    MIN_VACANCY_TEXT_LEN,
    Job,
    job_needs_vacancy_text,
    job_record_needs_vacancy_text,
)


def test_job_needs_vacancy_text_empty_no_score() -> None:
    assert job_needs_vacancy_text(vacancy_text="", overall_score=None) is True
    assert job_needs_vacancy_text(vacancy_text="   ", overall_score=None) is True
    assert (
        job_needs_vacancy_text(
            vacancy_text="x" * (MIN_VACANCY_TEXT_LEN - 1), overall_score=None
        )
        is True
    )


def test_job_needs_vacancy_text_has_score_or_text() -> None:
    assert job_needs_vacancy_text(vacancy_text="", overall_score=70) is False
    long = "x" * MIN_VACANCY_TEXT_LEN
    assert job_needs_vacancy_text(vacancy_text=long, overall_score=None) is False


def test_job_record_needs_vacancy_text() -> None:
    stub = Job(vacancy_text="", overall_score=None)
    assert job_record_needs_vacancy_text(stub) is True
    scored = Job(vacancy_text="", overall_score=55)
    assert job_record_needs_vacancy_text(scored) is False


def test_empty_unscored_ttl_hours() -> None:
    assert EMPTY_UNSCORED_TTL_HOURS == 6
