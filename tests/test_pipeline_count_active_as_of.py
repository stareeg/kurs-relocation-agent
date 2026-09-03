"""`count_active_as_of` — реконструкция активного счёта воронки на дату (Э9.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from core.domains.pipeline.analytics import count_active_as_of

_NOW = datetime(2026, 8, 26, tzinfo=UTC)
_CUTOFF = _NOW - timedelta(days=30)


def test_now_counts_by_current_status() -> None:
    jobs = [(1, "Скрининг"), (2, "Отказ"), (3, "Отклик"), (4, "Просмотрено")]
    assert count_active_as_of(jobs, [], None) == 2  # Скрининг + Отклик


def test_cutoff_reconstructs_from_stage_history_not_current_status() -> None:
    """jobs.status отражает только «сейчас» — для прошлого смотрим только на историю."""
    jobs = [(1, "Оффер")]  # текущий статус — не должен участвовать при cutoff != None
    stages = [
        (1, "Отклик", _NOW - timedelta(days=40)),
        (1, "Скрининг", _NOW - timedelta(days=35)),
        (1, "Техничка", _NOW - timedelta(days=10)),  # после cutoff — не в окне
    ]
    # На cutoff (30 дней назад) последняя строка ≤ cutoff — «Скрининг» (35 дней назад).
    assert count_active_as_of(jobs, stages, _CUTOFF) == 1


def test_stage_after_cutoff_excluded() -> None:
    jobs: list[tuple[int, str | None]] = []
    stages = [(1, "Скрининг", _NOW - timedelta(days=5))]  # позже cutoff
    assert count_active_as_of(jobs, stages, _CUTOFF) == 0


def test_terminal_stage_before_cutoff_not_active() -> None:
    jobs: list[tuple[int, str | None]] = []
    stages = [
        (1, "Отклик", _NOW - timedelta(days=40)),
        (1, "Отказ", _NOW - timedelta(days=35)),
    ]
    assert count_active_as_of(jobs, stages, _CUTOFF) == 0


def test_no_history_before_cutoff_not_counted() -> None:
    jobs: list[tuple[int, str | None]] = []
    assert count_active_as_of(jobs, [], _CUTOFF) == 0


def test_none_changed_at_ignored() -> None:
    jobs: list[tuple[int, str | None]] = []
    stages = [(1, "Скрининг", None)]
    assert count_active_as_of(jobs, stages, _CUTOFF) == 0
