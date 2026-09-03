"""Unit-тесты извлечения текста из PDF для parse_pdf."""

from __future__ import annotations

import pytest

from core.domains.profile.model import Experience, Personal, ResumeData, SearchCriteria
from core.domains.profile.parse_pdf import (
    ResumePdfLlmOut,
    ResumePdfParseError,
    coerce_date_to_iso,
    coerce_experience_industries,
    coerce_resume_dates,
    extract_pdf_text,
    finalize_pdf_search_axes,
)
from core.domains.profile.search_profile_suggest import coerce_experience_industry


def test_extract_pdf_rejects_non_pdf() -> None:
    with pytest.raises(ResumePdfParseError, match="не похож на PDF"):
        extract_pdf_text(b"not a pdf")


def test_extract_pdf_rejects_empty_pdf_bytes() -> None:
    with pytest.raises(ResumePdfParseError):
        extract_pdf_text(b"%PDF-1.4\n")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("2024-03", "2024-03"),
        ("2024-03-15", "2024-03-15"),
        ("Март 2024", "2024-03"),
        ("май 2020", "2020-05"),
        ("03.2024", "2024-03"),
        ("15.03.1990", "1990-03-15"),
        ("неизвестно", "неизвестно"),
    ],
)
def test_coerce_date_to_iso(raw: str, expected: str) -> None:
    assert coerce_date_to_iso(raw) == expected


def test_coerce_resume_dates_updates_nested_fields() -> None:
    data = ResumeData(
        personal=Personal(birth_date="1.02.1990"),
        experience=[Experience(start="Март 2024", end="", current=True)],
    )
    out = coerce_resume_dates(data)
    assert out.personal.birth_date == "1990-02-01"
    assert out.experience[0].start == "2024-03"


def test_finalize_pdf_search_axes_empty_ok() -> None:
    """Пустые новые поля допустимы — не падаем и не выдумываем."""
    raw = ResumePdfLlmOut()
    out = finalize_pdf_search_axes(raw)
    assert out.search_criteria.role_kind == ""
    assert out.search_criteria.market_segment == ""
    assert out.search_criteria.niches == []
    assert out.position.salary_basis == ""


def test_finalize_pdf_search_axes_maps_explicit_values() -> None:
    raw = ResumePdfLlmOut(
        search_criteria=SearchCriteria(
            role_kind="управляю людьми",
            market_segment="медиа / продакшн",
            niches=[],
        ),
        priorities=["Agile delivery", "Стейкхолдеры", "  ", "Roadmap"],
    )
    out = finalize_pdf_search_axes(raw)
    assert out.search_criteria.role_kind == "Управляю людьми"
    assert out.search_criteria.market_segment == "Медиа / Продакшн"
    assert out.search_criteria.niches == ["Agile delivery", "Стейкхолдеры", "Roadmap"]
    assert isinstance(out, ResumeData)
    assert not isinstance(out, ResumePdfLlmOut)


def test_finalize_pdf_priorities_ignored_when_niches_present() -> None:
    raw = ResumePdfLlmOut(
        search_criteria=SearchCriteria(
            role_kind="Делаю руками",
            market_segment="IT",
            niches=["Frontend", "Design systems"],
        ),
        priorities=["Не должно попасть"],
    )
    out = finalize_pdf_search_axes(raw)
    assert out.search_criteria.niches == ["Frontend", "Design systems"]
    assert out.search_criteria.role_kind == "Делаю руками"
    assert out.search_criteria.market_segment == "IT"


def test_finalize_pdf_does_not_touch_salary_basis() -> None:
    from core.domains.profile.model import DesiredPosition

    raw = ResumePdfLlmOut(
        position=DesiredPosition(salary_basis="До вычета", salary_min=200_000),
        search_criteria=SearchCriteria(role_kind="Делаю руками"),
    )
    out = finalize_pdf_search_axes(raw)
    assert out.position.salary_basis == "До вычета"


def test_coerce_experience_industry_maps_unknown_and_any_to_other() -> None:
    assert coerce_experience_industry("") == ""
    assert coerce_experience_industry("  ") == ""
    assert coerce_experience_industry("IT") == "IT"
    assert coerce_experience_industry("банки / финтех") == "Банки / Финтех"
    assert coerce_experience_industry("Любые") == "Другое"
    assert coerce_experience_industry("непонятная ниша") == "Другое"


def test_coerce_experience_industries_updates_rows() -> None:
    data = ResumeData(
        experience=[
            Experience(company="A", industry="IT"),
            Experience(company="B", industry="Любые"),
            Experience(company="C", industry=""),
        ]
    )
    out = coerce_experience_industries(data)
    assert [e.industry for e in out.experience] == ["IT", "Другое", ""]


def test_finalize_pdf_unknown_role_kind_cleared() -> None:
    raw = ResumePdfLlmOut(
        search_criteria=SearchCriteria(role_kind="кто-то ещё"),
        priorities=["A", "B", "C", "D", "E", "F", "G"],
    )
    out = finalize_pdf_search_axes(raw)
    assert out.search_criteria.role_kind == ""
    assert len(out.search_criteria.niches) == 6
