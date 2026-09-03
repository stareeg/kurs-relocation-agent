"""TB-4.3 / TB-4.7: сводка батча по фикстурным ScoreResult — счётчики, топ, пороги."""

from __future__ import annotations

from bot_app.services.batch_summary import (
    BatchScoreRow,
    count_batch_stats,
    format_batch_summary,
    is_card_worthy,
    progress_text,
    row_from_score,
)
from core.domains.opportunities.models import (
    BurnoutRisk,
    GradeMatch,
    RemoteAbroadCompat,
    RoleContentMatch,
    SalaryInfo,
    ScoreResult,
)


def _score(
    overall: int,
    recommendation: str,
) -> ScoreResult:
    """Минимальная фикстура ScoreResult (остальные поля — нейтральные заглушки)."""
    return ScoreResult(
        overall_score=overall,
        recommendation=recommendation,  # type: ignore[arg-type]
        remote_abroad_compat=RemoteAbroadCompat(level="ok", reasoning="r"),
        grade_match=GradeMatch(level="match", reasoning="r"),
        salary=SalaryInfo(meets_min=True, value_or_range="x", note=""),
        role_content_match=RoleContentMatch(score=70, matched_niche=[], reasoning="r"),
        burnout_risk=BurnoutRisk(level="low", reasoning="r"),
        company_type="product",
        pros=["p"],
        cons=["c"],
        red_flags=[],
        one_line_verdict="v",
    )


def _row_from_fixture(
    overall: int,
    rec: str,
    *,
    company: str = "Acme",
    title: str = "PM",
    vacancy_id: str = "v1",
) -> BatchScoreRow:
    return row_from_score(
        _score(overall, rec),
        company=company,
        title=title,
        vacancy_id=vacancy_id,
    )


def test_row_from_score_maps_score_result_fields() -> None:
    score = _score(88, "strong_apply")
    row = row_from_score(score, company=" Co ", title=" Lead ", vacancy_id="hh_1")
    assert row == BatchScoreRow(
        overall_score=88,
        recommendation="strong_apply",
        company="Co",
        title="Lead",
        vacancy_id="hh_1",
    )


def test_is_card_worthy_only_apply_family() -> None:
    assert is_card_worthy("strong_apply")
    assert is_card_worthy("apply")
    assert not is_card_worthy("maybe")
    assert not is_card_worthy("skip")
    assert not is_card_worthy("unknown")


def test_count_batch_stats_from_score_results() -> None:
    rows = [
        _row_from_fixture(90, "strong_apply"),
        _row_from_fixture(75, "apply"),
        _row_from_fixture(70, "apply"),
        _row_from_fixture(40, "maybe"),
        _row_from_fixture(10, "skip"),
    ]
    stats = count_batch_stats(rows)
    assert stats.total == 5
    assert stats.strong == 1
    assert stats.apply == 2
    assert stats.skip == 2


def test_count_batch_stats_errors_count_as_skip() -> None:
    rows = [_row_from_fixture(80, "apply")]
    stats = count_batch_stats(rows, errors=2)
    assert stats.total == 3
    assert stats.apply == 1
    assert stats.skip == 2


def test_format_batch_summary_top_by_score_from_fixtures() -> None:
    rows = [
        _row_from_fixture(50, "maybe", company="Low", title="Intern"),
        _row_from_fixture(92, "strong_apply", company="TopCo", title="Lead"),
        _row_from_fixture(78, "apply", company="MidCo", title="PM"),
    ]
    text = format_batch_summary(rows, top_n=2)
    assert text.startswith("3 вакансий: 1 сильных / 1 подать / 1 мимо")
    lines = text.splitlines()
    assert "92 Сильный фит — TopCo — Lead" in lines[2]
    assert "78 Подать — MidCo — PM" in lines[3]
    assert "Intern" not in text


def test_format_batch_summary_default_top_n_is_five() -> None:
    rows = [_row_from_fixture(90 - i, "apply", company=f"C{i}", title=f"T{i}") for i in range(7)]
    text = format_batch_summary(rows)
    # 7 строк в топе не больше 5 (+ заголовок + пустая).
    bullet_lines = [ln for ln in text.splitlines() if ln.startswith("•")]
    assert len(bullet_lines) == 5
    assert "C0" in text and "C4" in text
    assert "C5" not in text and "C6" not in text


def test_format_batch_summary_with_errors() -> None:
    text = format_batch_summary([_row_from_fixture(60, "skip")], errors=1)
    assert text.startswith("2 вакансий: 0 сильных / 0 подать / 2 мимо")
    assert "Ошибок оценки: 1" in text


def test_format_batch_summary_all_errors() -> None:
    text = format_batch_summary([], errors=3)
    assert text.startswith("3 вакансий: 0 сильных / 0 подать / 3 мимо")
    assert "Ошибок оценки: 3" in text
    assert "Нечего показать" not in text


def test_format_batch_summary_empty_no_errors() -> None:
    text = format_batch_summary([])
    assert "0 вакансий" in text
    assert "Нечего показать." in text


def test_card_worthy_thresholds_align_with_summary_buckets() -> None:
    """Порог карточек = strong_apply|apply; остальное в «мимо» сводки."""
    rows = [
        _row_from_fixture(95, "strong_apply"),
        _row_from_fixture(70, "apply"),
        _row_from_fixture(55, "maybe"),
        _row_from_fixture(20, "skip"),
    ]
    stats = count_batch_stats(rows)
    card_n = sum(1 for r in rows if is_card_worthy(r.recommendation))
    assert card_n == stats.strong + stats.apply == 2
    assert stats.skip == 2


def test_progress_text() -> None:
    assert progress_text(0, 5) == "Читаю 5 постов… 0/5"
    assert progress_text(3, 5) == "Читаю 5 постов… 3/5"
