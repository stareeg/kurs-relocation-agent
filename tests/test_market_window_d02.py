"""D-02: воронка перестаёт быть безусловно всевременной — окно по `jobs.created_at` +
`application_stages.changed_at`, ключ кэша снимка получает суффикс окна."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.market.analytics_cache import _snapshot_key
from core.domains.market.search_metrics import _window_start, _windowed

_NOW = datetime(2026, 8, 1, tzinfo=UTC)


def test_window_start_none_or_zero_means_all_time():
    assert _window_start(None) is None
    assert _window_start(0) is None
    assert _window_start(-5) is None


def test_window_start_is_days_ago():
    start = _window_start(30)
    assert start is not None
    assert (datetime.now(UTC) - start).days in (29, 30)  # без флейка на границе секунды


def test_all_time_window_returns_input_unchanged():
    jobs = [(1, "Отклик", _NOW - timedelta(days=60))]
    stages = [(1, "Отклик", _NOW - timedelta(days=60))]
    windowed_jobs, windowed_stages = _windowed(jobs, stages, None)
    assert windowed_jobs == jobs
    assert windowed_stages == stages


def test_three_windows_give_three_different_stage_sets():
    # A — создана 2 дня назад, B — 20 дней назад, C — 60 дней назад.
    jobs = [
        (1, "Отклик", _NOW - timedelta(days=2)),
        (2, "Скрининг", _NOW - timedelta(days=20)),
        (3, "Оффер", _NOW - timedelta(days=60)),
    ]
    stages = [
        (1, "Отклик", _NOW - timedelta(days=2)),
        (2, "Отклик", _NOW - timedelta(days=20)),
        (2, "Скрининг", _NOW - timedelta(days=19)),
        (3, "Отклик", _NOW - timedelta(days=60)),
        (3, "Оффер", _NOW - timedelta(days=58)),
    ]

    jobs_7, stages_7 = _windowed(jobs, stages, _NOW - timedelta(days=7))
    jobs_30, stages_30 = _windowed(jobs, stages, _NOW - timedelta(days=30))
    jobs_90, stages_90 = _windowed(jobs, stages, _NOW - timedelta(days=90))

    assert {j[0] for j in jobs_7} == {1}
    assert {j[0] for j in jobs_30} == {1, 2}
    assert {j[0] for j in jobs_90} == {1, 2, 3}

    assert len(stages_7) == 1
    assert len(stages_30) == 3
    assert len(stages_90) == 5

    # Три окна — три разных набора ступеней (не совпадающих друг с другом).
    assert {j[0] for j in jobs_7} != {j[0] for j in jobs_30} != {j[0] for j in jobs_90}


def test_stage_change_alone_does_not_rescue_a_job_created_outside_window():
    # Вакансия создана 60 дней назад, но по ней вчера пришёл переход этапа — окно 30 дней всё
    # равно не должно её подхватывать: фильтр по created_at И changed_at одновременно (не «или»).
    jobs = [(1, "Скрининг", _NOW - timedelta(days=60))]
    stages = [(1, "Скрининг", _NOW - timedelta(days=1))]
    windowed_jobs, windowed_stages = _windowed(jobs, stages, _NOW - timedelta(days=30))
    assert windowed_jobs == []
    assert windowed_stages == []


def test_snapshot_key_all_time_matches_bare_kind():
    # Фоновый пересчёт (snapshot_refresh.py) не передаёт days — ключ не должен уехать от
    # исторического "search"/"pulse"/"grid".
    assert _snapshot_key("search", None) == "search"
    assert _snapshot_key("search", 0) == "search"


def test_snapshot_key_gets_window_suffix():
    assert _snapshot_key("search", 7) == "search:7"
    assert _snapshot_key("search", 30) == "search:30"
    assert _snapshot_key("search", 90) == "search:90"


async def test_save_and_load_snapshot_use_windowed_key(monkeypatch: Any):
    calls: list[tuple[str, tuple[Any, ...]]] = []

    class FakeDb:
        async def execute(self, sql: str, *args: Any) -> None:
            calls.append((sql, args))

        async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
            calls.append((sql, args))
            return None

    from core.domains.market.analytics_cache import load_snapshot, save_snapshot

    db = FakeDb()
    await save_snapshot("search", {"a": 1}, account_id=1, days=30, db=db)
    await load_snapshot("search", account_id=1, days=30, db=db)

    assert calls[0][1][1] == "search:30"
    assert calls[1][1][1] == "search:30"
