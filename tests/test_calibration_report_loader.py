"""B-02: калибровка скоринга — чистый compute + загрузчик."""

from __future__ import annotations

from typing import Any

import pytest

from core.domains.market.relevance import CalibrationReport, compute_calibration_report


def test_monotonic_conversion_growth_on_synthetic_rows() -> None:
    """Выше корзина балла → выше конверсия в скрининг (скоринг калиброван)."""
    rows = [
        (90, 3),
        (85, 3),
        (95, 6),
        (82, 3),  # 80–100: applied=4, responded=4 → 1.0
        (70, 3),
        (75, 3),
        (65, 2),
        (68, 2),  # 60–79: applied=4, responded=2 → 0.5
        (50, 3),
        (45, 2),
        (55, 2),  # 40–59: applied=3, responded=1 → ~0.333
        (20, 2),
        (10, 2),  # 0–39: applied=2, responded=0 → 0.0
    ]
    report = compute_calibration_report(rows)
    assert report.available is True
    assert report.enough_data is True
    assert report.note is None
    assert report.applied == 13
    assert report.responded == 7
    assert report.offers == 1

    rates = [b.conversion_rate for b in report.bands]
    assert rates == [1.0, 0.5, pytest.approx(1 / 3, abs=1e-4), 0.0]
    # Корзины идут от высокого балла к низкому — конверсия не растёт вниз.
    assert rates[0] >= rates[1] >= rates[2] >= rates[3]


def test_enough_data_false_at_9_applied() -> None:
    """Порог: applied ≥ 10. Девять откликов — плашка, выводов нет."""
    rows = [(80, 2)] * 9
    report = compute_calibration_report(rows)
    assert report.available is True
    assert report.enough_data is False
    assert report.applied == 9
    assert report.responded == 0
    assert report.note is not None
    assert "9" in report.note


def test_empty_rows_unavailable() -> None:
    assert compute_calibration_report([]).available is False


class _FakeDb:
    """Минимальный Executor: отдаёт заранее заданные jobs / application_stages."""

    def __init__(self, jobs: list[dict[str, Any]], stages: list[dict[str, Any]]) -> None:
        self._jobs = jobs
        self._stages = stages

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        q = " ".join(query.lower().split())
        if "from application_stages" in q:
            return self._stages
        if "from jobs" in q:
            return self._jobs
        raise AssertionError(f"неожиданный SQL: {query}")


@pytest.mark.asyncio
async def test_loader_builds_furthest_stage_and_skips_unscored() -> None:
    """Загрузчик: overall_score + max ступень из status/истории."""
    from core.domains.market.service import get_calibration_report

    db = _FakeDb(
        jobs=[
            {"id": 1, "overall_score": 90, "status": "Отклик"},
            {"id": 2, "overall_score": 70, "status": "Просмотр"},
        ],
        stages=[
            {"job_id": 1, "stage": "Скрининг"},
            {"job_id": 1, "stage": "Оффер"},
        ],
    )
    report = await get_calibration_report(account_id=1, db=db)
    assert report.available is True
    assert report.applied == 1  # только job 1 дошёл до applied+
    assert report.responded == 1
    assert report.offers == 1


@pytest.mark.asyncio
async def test_loader_without_pg_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет пула Postgres → available=false, не 500."""
    import core.platform.db.pool as pool_mod
    from core.domains.market.service import get_calibration_report

    monkeypatch.setattr(
        pool_mod, "get_pool", lambda: (_ for _ in ()).throw(RuntimeError("no pg"))
    )
    report = await get_calibration_report(account_id=1)
    assert isinstance(report, CalibrationReport)
    assert report.available is False
