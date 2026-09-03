"""Шаг 23: зарплатные корзины рынка от profile.salary_min."""

from __future__ import annotations

from core.domains.market.market import compute_market_slices, salary_bands_net


def test_salary_bands_net_for_250k() -> None:
    bands = salary_bands_net(250_000)
    assert bands is not None
    labels = [lab for _, _, lab in bands]
    assert labels == ["до 175к", "175-250к", "250-350к", "350к+"]
    # Границы: <0.7×, 0.7–1.0×, 1.0–1.4×, >1.4×
    assert bands[0] == (0, 174_999, "до 175к")
    assert bands[1][0] == 175_000 and bands[1][1] == 249_999
    assert bands[2][0] == 250_000 and bands[2][1] == 350_000
    assert bands[3][0] == 350_001


def test_salary_bands_net_unset() -> None:
    assert salary_bands_net(0) is None
    assert salary_bands_net(-1) is None


def test_compute_slices_without_salary_min_marks_bands_unavailable() -> None:
    rows = [
        (
            {
                "overall_score": 70,
                "salary": {"meets_min": True, "estimated_min": 200_000, "estimated_max": 220_000},
            },
            {"meets_min": True, "estimated_min": 200_000, "estimated_max": 220_000},
            {"verdict": "real"},
        )
    ]
    slices = compute_market_slices(rows, salary_min=0)
    assert slices.available is True
    assert slices.salary_bands_available is False
    assert len(slices.salary_bands) == 1
    assert slices.salary_bands[0].label == "все"


def test_compute_slices_bands_from_salary_min() -> None:
    # mid net ≈ gross_to_net((200k+220k)/2) — попадание в какую-то корзину 250к-якоря.
    rows = [
        (
            {"overall_score": 70},
            {"meets_min": False, "estimated_min": 200_000, "estimated_max": 220_000},
            None,
        ),
        (
            {"overall_score": 80},
            {"meets_min": True, "estimated_min": 400_000, "estimated_max": 420_000},
            None,
        ),
    ]
    slices = compute_market_slices(rows, salary_min=250_000)
    assert slices.salary_bands_available is True
    assert all(b.label != "все" for b in slices.salary_bands)
    assert sum(b.count for b in slices.salary_bands) == 2


def test_compute_slices_grade_levels_canonical_ladder_from_target() -> None:
    rows = [
        ({"overall_score": 70, "grade_match": {"level": "match"}}, {}, None),
        ({"overall_score": 70, "grade_match": {"level": "match"}}, {}, None),
        ({"overall_score": 70, "grade_match": {"level": "above"}}, {}, None),
        ({"overall_score": 70, "grade_match": {"level": "far_below"}}, {}, None),
    ]
    slices = compute_market_slices(rows, salary_min=0, grade_floor=2, grade_ceil=2)
    assert [(b.label, b.count) for b in slices.grade_levels] == [
        ("Junior", 1),
        ("Senior", 2),
        ("Lead", 1),
    ]


def test_compute_slices_grade_levels_prefers_reasoning_name() -> None:
    rows = [
        (
            {"overall_score": 70, "grade_match": {"level": "match", "reasoning": "Middle backend"}},
            {},
            None,
        ),
    ]
    slices = compute_market_slices(rows, salary_min=0, grade_floor=2, grade_ceil=2)
    assert [(b.label, b.count) for b in slices.grade_levels] == [("Middle", 1)]


def test_compute_slices_grade_levels_empty_without_grade_match() -> None:
    rows = [({"overall_score": 70}, {}, None)]
    slices = compute_market_slices(rows, salary_min=0)
    assert slices.grade_levels == []
