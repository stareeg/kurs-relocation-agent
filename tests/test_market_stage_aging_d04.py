"""D-04: возраст вакансий в активных этапах — `compute_stage_aging`, чистая функция."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domains.market.stage_aging import compute_stage_aging

_NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _ago(days: int) -> datetime:
    return _NOW - timedelta(days=days)


def test_no_active_jobs_gives_empty_rows_for_every_stage():
    result = compute_stage_aging([], [], now=_NOW)
    assert result.available is True
    assert result.total_active == 0
    assert [row.stage for row in result.rows] == ["Скрининг", "Техничка", "Финал", "Оффер"]
    assert all(row.total == 0 for row in result.rows)
    assert result.stalled == []


def test_only_active_stages_counted_not_applied_or_rejected():
    jobs = [
        (1, "Отклик", "A", "vac-a", 80),
        (2, "Отказ", "B", "vac-b", 70),
        (3, "Скрининг", "C", "vac-c", 90),
    ]
    stages = [(3, "Скрининг", _ago(1))]
    result = compute_stage_aging(jobs, stages, now=_NOW)
    assert result.total_active == 1
    by_stage = {row.stage: row.total for row in result.rows}
    assert by_stage == {"Скрининг": 1, "Техничка": 0, "Финал": 0, "Оффер": 0}


def test_age_buckets_split_by_days_since_last_stage_change():
    jobs = [
        (1, "Скрининг", "A", "a", 80),  # 3 дня → «до 7 дней»
        (2, "Скрининг", "B", "b", 80),  # 10 дней → «1–2 недели»
        (3, "Скрининг", "C", "c", 80),  # 18 дней → «2–3 недели»
        (4, "Скрининг", "D", "d", 80),  # 25 дней → «больше 3 недель»
    ]
    stages = [
        (1, "Скрининг", _ago(3)),
        (2, "Скрининг", _ago(10)),
        (3, "Скрининг", _ago(18)),
        (4, "Скрининг", _ago(25)),
    ]
    result = compute_stage_aging(jobs, stages, now=_NOW)
    screening = next(row for row in result.rows if row.stage == "Скрининг")
    counts = {bucket.label: bucket.count for bucket in screening.buckets}
    assert counts == {
        "до 7 дней": 1,
        "1–2 недели": 1,
        "2–3 недели": 1,
        "больше 3 недель": 1,
    }
    assert screening.total == 4


def test_sum_of_stage_totals_equals_active_count():
    jobs = [
        (1, "Скрининг", "A", "a", 80),
        (2, "Скрининг", "B", "b", 80),
        (3, "Техничка", "C", "c", 80),
        (4, "Финал", "D", "d", 80),
        (5, "Оффер", "E", "e", 80),
    ]
    stages = [
        (1, "Скрининг", _ago(2)),
        (2, "Скрининг", _ago(4)),
        (3, "Техничка", _ago(6)),
        (4, "Финал", _ago(8)),
        (5, "Оффер", _ago(10)),
    ]
    result = compute_stage_aging(jobs, stages, now=_NOW)
    assert result.total_active == 5
    assert sum(row.total for row in result.rows) == result.total_active


def test_stalled_threshold_is_stage_median_times_two_not_a_constant():
    # Медиана этапа = 4 дня → порог 8: только вакансия на 20 днях залежалась.
    jobs = [
        (1, "Скрининг", "A", "a", 80),
        (2, "Скрининг", "B", "b", 80),
        (3, "Скрининг", "C", "c", 80),
    ]
    stages = [
        (1, "Скрининг", _ago(2)),
        (2, "Скрининг", _ago(4)),
        (3, "Скрининг", _ago(20)),
    ]
    result = compute_stage_aging(jobs, stages, now=_NOW)
    assert [item.job_id for item in result.stalled] == [3]
    assert result.stalled[0].days == 20
    assert result.stalled[0].company == "C"


def test_stalled_capped_at_five_sorted_by_days_desc():
    # 7 свежих (1 день, медиана всей выборки садится в этот кластер → порог 2) и 6 старых
    # (100 дней, все проходят порог) — 6 кандидатов «залежались», но список режется до 5.
    fresh = [(i, "Скрининг", f"F{i}", f"f{i}", 80) for i in range(1, 8)]
    old = [(i, "Скрининг", f"O{i}", f"o{i}", 80) for i in range(8, 14)]
    jobs = fresh + old
    stages = [(i, "Скрининг", _ago(1)) for i in range(1, 8)] + [
        (i, "Скрининг", _ago(100)) for i in range(8, 14)
    ]
    result = compute_stage_aging(jobs, stages, now=_NOW)
    assert len(result.stalled) == 5
    days = [item.days for item in result.stalled]
    assert days == sorted(days, reverse=True)
    assert all(item.days == 100 for item in result.stalled)


def test_job_without_any_stage_history_is_excluded():
    # Активный статус, но ни одной строки application_stages — нет точки отсчёта возраста.
    jobs = [(1, "Скрининг", "A", "a", 80)]
    result = compute_stage_aging(jobs, [], now=_NOW)
    assert result.total_active == 0
