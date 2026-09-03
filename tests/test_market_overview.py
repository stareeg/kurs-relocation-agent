"""D-01: двухуровневая воронка `compute_overview_funnel` (правка 2.3 плана) — чистая функция.

E-03: `_load_market_index` — индекс рынка из `external_signals` в форму ответа «Рынка»."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.market.overview import (
    _load_market_index,
    compute_overview_funnel,
    compute_period_funnel_bars,
)


def test_empty_when_nobody_applied():
    assert compute_overview_funnel(applied_total=0, active_statuses=[]) == []


def test_two_rows_each_normalized_to_its_own_base():
    # 85 откликов, из них 18 сейчас в работе (скрининг 11, техничка 4, финал 1, оффер 2).
    active_statuses = (
        ["Скрининг"] * 11 + ["Техничка"] * 4 + ["Финал"] * 1 + ["Оффер"] * 2 + ["Отклик"] * 67
    )
    rows = compute_overview_funnel(applied_total=85, active_statuses=active_statuses)

    assert len(rows) == 2
    responses, in_progress = rows

    assert responses.label == "Отклики"
    assert responses.base == 85
    assert sum(s.count for s in responses.segments) == responses.base
    by_key = {s.key: s.count for s in responses.segments}
    assert by_key == {"no_answer": 67, "in_progress": 18}

    # Вторая строка перенормирована на свои 18 — база строки == сегмент «в работе» первой строки.
    assert in_progress.label == "В работе"
    assert in_progress.base == 18 == by_key["in_progress"]
    assert sum(s.count for s in in_progress.segments) == in_progress.base
    stage_counts = {s.key: s.count for s in in_progress.segments}
    assert stage_counts == {
        "Скрининг": 11,
        "Техничка": 4,
        "Финал": 1,
        "Оффер": 2,
    }


def test_rejected_and_silent_both_land_in_no_answer_segment():
    # Отклонили после техпрогона и просто молчат — оба не «в работе» сейчас, но applied_total
    # это учитывал: без ответа = applied_total - в работе, без деления на «было/не было».
    active_statuses = ["Отказ", "Отклик"]
    rows = compute_overview_funnel(applied_total=5, active_statuses=active_statuses)
    responses = rows[0]
    by_key = {s.key: s.count for s in responses.segments}
    assert by_key["in_progress"] == 0
    assert by_key["no_answer"] == 5
    # Никто сейчас не в работе — второй строки нет (пустая база ничего не объясняет).
    assert len(rows) == 1


def test_row_without_second_level_omitted_when_nobody_in_progress():
    rows = compute_overview_funnel(applied_total=3, active_statuses=["Отклик", "Отклик", "Отклик"])
    assert len(rows) == 1
    assert rows[0].segments[1].count == 0


def test_period_funnel_bars_counts_distinct_jobs_in_window():
    now = datetime(2026, 8, 11, tzinfo=UTC)
    start, end = now - timedelta(days=14), now
    stages = [
        (1, "Скрининг", now - timedelta(days=5)),
        (2, "Скрининг", now - timedelta(days=3)),
        # Та же вакансия дважды заходит в скрининг за период — считаем один раз.
        (2, "Скрининг", now - timedelta(days=1)),
        (3, "Техничка", now - timedelta(days=2)),
        (4, "Оффер", now - timedelta(days=1)),
        (5, "Финал", now - timedelta(days=4)),
        # За пределами окна — не считаем.
        (6, "Скрининг", now - timedelta(days=30)),
    ]
    bars = compute_period_funnel_bars(stages=stages, period_start=start, period_end=end)
    by_label = {b.label: b.count for b in bars}
    # Правка 2026-08-14: все четыре стадии отдаются всегда (включая нулевые), плюс Финал.
    assert by_label == {"Скрининги": 2, "Технички": 1, "Финалы": 1, "Офферы": 1}


def test_period_funnel_bars_empty_outside_window():
    now = datetime(2026, 8, 11, tzinfo=UTC)
    stages = [(1, "Скрининг", now - timedelta(days=30))]
    bars = compute_period_funnel_bars(
        stages=stages, period_start=now - timedelta(days=14), period_end=now
    )
    # Все корзины нулевые, но ряд всё равно полный — фронт рисует честный «0» по каждой стадии.
    by_label = {b.label: b.count for b in bars}
    assert by_label == {"Скрининги": 0, "Технички": 0, "Финалы": 0, "Офферы": 0}


def test_period_funnel_bars_naive_timestamps_treated_as_utc():
    now = datetime(2026, 8, 11, tzinfo=UTC)
    stages = [(1, "Скрининг", datetime(2026, 8, 9))]  # naive, внутри окна как UTC
    bars = compute_period_funnel_bars(
        stages=stages, period_start=now - timedelta(days=14), period_end=now
    )
    assert {b.label: b.count for b in bars}["Скрининги"] == 1


class _FakeDb:
    def __init__(self, row: dict[str, Any] | None):
        self._row = row

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        return self._row


async def test_load_market_index_empty_when_no_reading():
    point = await _load_market_index(db=_FakeDb(None))
    assert point.available is False


async def test_load_market_index_available_with_zone_and_date():
    captured_at = datetime.now(UTC) - timedelta(days=5)
    db = _FakeDb(
        {"id": 1, "month": captured_at.date(), "value": 9.6, "source": "manual", "captured_at": captured_at}
    )
    point = await _load_market_index(db=db)
    assert point.available is True
    assert point.value == 9.6
    assert point.zone == "высокая конкуренция"
    assert point.captured_at == captured_at


async def test_load_market_index_hidden_when_stale_past_two_months():
    # Риск 3 плана: владелец забыл ввести значение — старше двух месяцев прячем, не показываем протухшее.
    captured_at = datetime.now(UTC) - timedelta(days=70)
    db = _FakeDb(
        {"id": 1, "month": captured_at.date(), "value": 5.0, "source": "manual", "captured_at": captured_at}
    )
    point = await _load_market_index(db=db)
    assert point.available is False
