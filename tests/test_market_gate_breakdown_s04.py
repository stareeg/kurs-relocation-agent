"""S-04: взаимоисключающая сегментация «Что режет поток» — `compute_gate_breakdown`, чистая."""

from __future__ import annotations

from core.domains.market.relevance import compute_gate_breakdown
from core.domains.profile.profile import SearchProfile


def _row(*, salary=False, remote=False, grade=False, stack=False, score: int = 70) -> tuple:
    sd = {
        "salary": {"meets_min": not salary},
        "remote_abroad_compat": {"level": "blocker" if remote else "ok"},
        "grade_match": {"level": "far_below" if grade else "match"},
        "role_content_match": {"score": 20 if stack else 90},
    }
    return (score, sd)


def test_no_rows_gives_empty_list():
    assert compute_gate_breakdown([]) == []


def test_unscored_rows_excluded():
    rows = [(None, {})]
    assert compute_gate_breakdown(rows) == []


def test_all_passed_single_segment():
    rows = [_row(), _row(), _row()]
    result = compute_gate_breakdown(rows)
    assert len(result) == 1
    assert result[0].key == "passed"
    assert result[0].count == 3
    assert result[0].pct == 100.0


def test_each_vacancy_counted_in_exactly_one_segment():
    # Одна упала по зарплате, одна — по формату, одна прошла оба гейта.
    rows = [_row(salary=True), _row(remote=True), _row()]
    result = compute_gate_breakdown(rows)
    by_key = {s.key: s.count for s in result}
    assert by_key == {"salary": 1, "remote": 1, "passed": 1}
    # Сегменты взаимоисключающие — сумма равна числу заскоренных вакансий без остатка.
    assert sum(by_key.values()) == len(rows)


def test_vacancy_failing_two_gates_counts_once_by_priority_order():
    # Упала и по зарплате, и по формату — приоритет «зарплата → формат → грейд → роль»,
    # поэтому идёт в «salary», не задваивается в двух сегментах (в отличие от kill_factors).
    rows = [_row(salary=True, remote=True)]
    result = compute_gate_breakdown(rows)
    assert len(result) == 1
    assert result[0].key == "salary"
    assert result[0].count == 1


def test_segments_with_zero_count_are_omitted():
    rows = [_row(), _row()]
    result = compute_gate_breakdown(rows)
    keys = {s.key for s in result}
    assert keys == {"passed"}
    assert "salary" not in keys


def test_labels_follow_profile():
    rows = [_row(salary=True)]
    profile = SearchProfile(salary_min=250_000)
    result = compute_gate_breakdown(rows, profile=profile)
    by_key = {s.key: s.label for s in result}
    assert by_key["salary"] == "Зарплата ниже 250к"
