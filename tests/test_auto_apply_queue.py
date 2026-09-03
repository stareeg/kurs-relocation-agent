"""`preview_queue` — живой пересчёт очереди автооткликов (Фаза 1, без персиста/отправки)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.domains.opportunities.jobs import Job
from core.domains.pipeline.auto_apply import queue as auto_apply_queue
from core.domains.pipeline.auto_apply.config import AutoApplyConfig, AutoApplyPlatformConfig
from core.kernel.schemas.funnel import FunnelStatus


def _job(vacancy_id: str, source: str | None, overall_score: int | None) -> Job:
    return Job(
        vacancy_id=vacancy_id,
        vacancy_text="x" * 60,
        source=source,
        status=FunnelStatus.VIEWED.value,
        overall_score=overall_score,
    )


async def test_preview_splits_by_decision_and_filters_by_platform(monkeypatch: pytest.MonkeyPatch):
    jobs = [
        _job("1", "vacancy_page", overall_score=90),  # hh, auto
        _job("2", "vacancy_page", overall_score=70),  # hh, manual_review
        _job("3", "vacancy_page", overall_score=10),  # hh, тоже ручной разбор (порог один)
        _job("gm_1", "getmatch", overall_score=90),  # другая площадка — не должна попасть
    ]
    config = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=True, min_score=75, manual_review_band=10)
    )
    monkeypatch.setattr(auto_apply_queue, "list_jobs", AsyncMock(return_value=jobs))
    monkeypatch.setattr(auto_apply_queue, "get_auto_apply_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        auto_apply_queue, "list_jobs_applied_today_via", AsyncMock(return_value=[])
    )

    result = await auto_apply_queue.preview_queue("hh", account_id=1)

    assert result.enabled is True
    assert [j.vacancy_id for j in result.auto] == ["1"]
    # Порог один: и 70, и 10 — ручной разбор; сортировка по скору убыванием.
    assert [j.vacancy_id for j in result.manual_review] == ["2", "3"]


async def test_preview_disabled_platform_reports_enabled_false(monkeypatch: pytest.MonkeyPatch):
    config = AutoApplyConfig()  # всё выключено по умолчанию
    monkeypatch.setattr(auto_apply_queue, "list_jobs", AsyncMock(return_value=[]))
    monkeypatch.setattr(auto_apply_queue, "get_auto_apply_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        auto_apply_queue, "list_jobs_applied_today_via", AsyncMock(return_value=[])
    )

    result = await auto_apply_queue.preview_queue("habr", account_id=1)

    assert result.enabled is False
    assert result.auto == []
    assert result.manual_review == []


async def test_preview_disabled_platform_still_shows_would_be_queue(
    monkeypatch: pytest.MonkeyPatch,
):
    """Пункт 1 редизайна «Расширения» (2026-08-19): очередь видна ВСЕГДА, не только пока площадка
    реально включена — `enabled=False` больше не гасит классификацию до пустого списка."""
    jobs = [
        _job("1", "vacancy_page", overall_score=90),  # auto
        _job("2", "vacancy_page", overall_score=70),  # manual_review
    ]
    config = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=False, min_score=75, manual_review_band=10)
    )
    monkeypatch.setattr(auto_apply_queue, "list_jobs", AsyncMock(return_value=jobs))
    monkeypatch.setattr(auto_apply_queue, "get_auto_apply_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        auto_apply_queue, "list_jobs_applied_today_via", AsyncMock(return_value=[])
    )

    result = await auto_apply_queue.preview_queue("hh", account_id=1)

    assert result.enabled is False
    assert [j.vacancy_id for j in result.auto] == ["1"]
    assert [j.vacancy_id for j in result.manual_review] == ["2"]


def _job_with(
    vacancy_id: str,
    *,
    overall_score: int | None,
    total_responses: int | None = None,
    published_at: str | None = None,
    company_canonical: str | None = None,
) -> Job:
    return Job(
        vacancy_id=vacancy_id,
        vacancy_text="x" * 60,
        source="vacancy_page",
        status=FunnelStatus.VIEWED.value,
        overall_score=overall_score,
        total_responses=total_responses,
        published_at=published_at,
        company_canonical=company_canonical,
    )


async def test_order_score_desc_is_default(monkeypatch: pytest.MonkeyPatch):
    jobs = [
        _job_with("1", overall_score=80),
        _job_with("2", overall_score=95),
        _job_with("3", overall_score=90),
    ]
    config = AutoApplyConfig(hh=AutoApplyPlatformConfig(enabled=True, min_score=75))
    monkeypatch.setattr(auto_apply_queue, "list_jobs", AsyncMock(return_value=jobs))
    monkeypatch.setattr(auto_apply_queue, "get_auto_apply_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        auto_apply_queue, "list_jobs_applied_today_via", AsyncMock(return_value=[])
    )

    result = await auto_apply_queue.preview_queue("hh", account_id=1)

    assert [j.vacancy_id for j in result.auto] == ["2", "3", "1"]


async def test_order_smart_penalizes_high_competition(monkeypatch: pytest.MonkeyPatch):
    """6.1: свежая вакансия с малой конкуренцией обгоняет ту же по скору, но перегретую."""
    jobs = [
        _job_with("crowded", overall_score=90, total_responses=200),
        _job_with("unknown", overall_score=90, total_responses=None),
        _job_with("quiet", overall_score=88, total_responses=1),
    ]
    config = AutoApplyConfig(hh=AutoApplyPlatformConfig(enabled=True, min_score=75, order="smart"))
    monkeypatch.setattr(auto_apply_queue, "list_jobs", AsyncMock(return_value=jobs))
    monkeypatch.setattr(auto_apply_queue, "get_auto_apply_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        auto_apply_queue, "list_jobs_applied_today_via", AsyncMock(return_value=[])
    )

    result = await auto_apply_queue.preview_queue("hh", account_id=1)

    order = [j.vacancy_id for j in result.auto]
    # unknown (нет данных — штраф 0) обгоняет crowded (тот же скор, но 200 откликов).
    assert order.index("unknown") < order.index("crowded")
    # quiet (чуть ниже скор, но почти нет конкуренции) обгоняет crowded.
    assert order.index("quiet") < order.index("crowded")


async def test_order_published_desc_newest_first(monkeypatch: pytest.MonkeyPatch):
    jobs = [
        _job_with("old", overall_score=90, published_at="1 января 2026"),
        _job_with("new", overall_score=90, published_at="21 мая 2026"),
        _job_with("no_date", overall_score=90, published_at=None),
    ]
    config = AutoApplyConfig(
        hh=AutoApplyPlatformConfig(enabled=True, min_score=75, order="published_desc")
    )
    monkeypatch.setattr(auto_apply_queue, "list_jobs", AsyncMock(return_value=jobs))
    monkeypatch.setattr(auto_apply_queue, "get_auto_apply_config", AsyncMock(return_value=config))
    monkeypatch.setattr(
        auto_apply_queue, "list_jobs_applied_today_via", AsyncMock(return_value=[])
    )

    result = await auto_apply_queue.preview_queue("hh", account_id=1)

    order = [j.vacancy_id for j in result.auto]
    assert order.index("new") < order.index("old") < order.index("no_date")
