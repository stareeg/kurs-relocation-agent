"""Канон специальностей резюме и миграция старых getmatch-слагов."""

from __future__ import annotations

from core.domains.profile.categories import RESUME_CATEGORIES, normalize_categories
from core.domains.profile.model import DesiredPosition, ResumeData


def test_eighteen_categories_nine_per_column() -> None:
    assert len(RESUME_CATEGORIES) == 18
    assert len(set(RESUME_CATEGORIES)) == 18
    assert "Project Management" in RESUME_CATEGORIES
    assert "Аналитика / Data" in RESUME_CATEGORIES
    assert "ML / DS / AI" in RESUME_CATEGORIES
    assert "КиберБез" in RESUME_CATEGORIES
    assert "Fullstack" in RESUME_CATEGORIES
    assert "Product/Project/Architecture" not in RESUME_CATEGORIES
    assert "1С" not in RESUME_CATEGORIES
    assert "HR / рекрутинг" not in RESUME_CATEGORIES
    assert "Продажи" not in RESUME_CATEGORIES
    assert "Data / ML" not in RESUME_CATEGORIES
    assert "Аналитика" not in RESUME_CATEGORIES
    assert "Информационная безопасность" not in RESUME_CATEGORIES


def test_legacy_slugs_map_on_resume_load() -> None:
    data = ResumeData(
        position=DesiredPosition(
            categories=["Project Manager", "QA", "UX & Tech Writers", "Design & UX"]
        )
    )
    assert data.position.categories == [
        "Project Management",
        "QA / тестирование",
        "Дизайн / UX",
    ]


def test_legacy_it_splits_and_drops_non_it() -> None:
    assert normalize_categories(["Data / ML", "Аналитика", "Информационная безопасность"]) == [
        "ML / DS / AI",
        "Аналитика / Data",
        "КиберБез",
    ]
    assert normalize_categories(["1С", "HR / рекрутинг", "Продажи", "Backend"]) == ["Backend"]


def test_normalize_drops_unknown_and_caps_at_three() -> None:
    assert normalize_categories(["Backend", "Frontend", "Mobile", "QA"]) == [
        "Backend",
        "Frontend",
        "Mobile",
    ]
    assert normalize_categories(["неизвестная ниша", "  "]) == []
