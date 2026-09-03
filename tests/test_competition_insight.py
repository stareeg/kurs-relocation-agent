"""Этап 6 §6.2 (plans/scoring_precision_2026_08_17.md): под-скор «шанс на отклик».

Чистая функция, без LLM/I-O — `total_responses`/`published_at`/`letter_required` → уровень
конкуренции. НЕ входит в overall_score (Этап 7 ещё не измерил корреляцию с исходами).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domains.opportunities.competition import compute_competition_insight


def _date_str(days_ago: int) -> str:
    d = datetime.now(UTC).date() - timedelta(days=days_ago)
    months = {
        1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
        7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
    }
    return f"{d.day} {months[d.month]} {d.year}"


def test_no_total_responses_is_unknown():
    result = compute_competition_insight(
        total_responses=None, published_at=_date_str(3), letter_required=False
    )
    assert result.level == "unknown"
    assert result.responses_per_day is None
    assert result.age_days is None


def test_low_rate_with_known_age_is_favorable():
    result = compute_competition_insight(
        total_responses=3, published_at=_date_str(10), letter_required=False
    )
    assert result.level == "favorable"
    assert result.age_days == 10
    assert result.responses_per_day == 0.3


def test_high_rate_with_known_age_is_crowded():
    result = compute_competition_insight(
        total_responses=100, published_at=_date_str(5), letter_required=False
    )
    assert result.level == "crowded"
    assert result.responses_per_day == 20.0


def test_mid_rate_is_neutral():
    result = compute_competition_insight(
        total_responses=15, published_at=_date_str(5), letter_required=False
    )
    assert result.level == "neutral"


def test_unparsable_published_at_falls_back_to_raw_thresholds():
    result = compute_competition_insight(
        total_responses=3, published_at="дата неизвестна", letter_required=False
    )
    assert result.level == "favorable"
    assert result.age_days is None
    assert result.responses_per_day is None
    assert "грубая" in result.reasoning


def test_no_published_at_falls_back_to_raw_thresholds():
    result = compute_competition_insight(
        total_responses=25, published_at=None, letter_required=False
    )
    assert result.level == "crowded"


def test_letter_required_softens_crowded_to_neutral():
    with_letter = compute_competition_insight(
        total_responses=100, published_at=_date_str(5), letter_required=True
    )
    without_letter = compute_competition_insight(
        total_responses=100, published_at=_date_str(5), letter_required=False
    )
    assert without_letter.level == "crowded"
    assert with_letter.level == "neutral"
    assert "сопроводительное" in with_letter.reasoning


def test_letter_required_softens_neutral_to_favorable():
    result = compute_competition_insight(
        total_responses=15, published_at=_date_str(5), letter_required=True
    )
    assert result.level == "favorable"


def test_letter_required_does_not_change_already_favorable():
    result = compute_competition_insight(
        total_responses=1, published_at=_date_str(10), letter_required=True
    )
    assert result.level == "favorable"
    assert "сопроводительное" not in result.reasoning


def test_published_today_does_not_divide_by_zero():
    result = compute_competition_insight(
        total_responses=5, published_at=_date_str(0), letter_required=False
    )
    assert result.age_days == 0
    assert result.responses_per_day == 5.0


def test_negative_total_responses_is_treated_as_unknown():
    result = compute_competition_insight(
        total_responses=-1, published_at=_date_str(5), letter_required=False
    )
    assert result.level == "unknown"
