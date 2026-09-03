"""FR2-41 / B-05: exclude-сет, реестр компаний, регистрация эндпоинтов."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.routing import iter_route_contexts

import pytest

from core.app.scenarios.companies import _with_verdict
from core.domains.opportunities.jobs import (
    CompanyRow,
    canonical_exclude_set,
    furthest_stage_label,
)
from core.kernel.schemas.funnel import FunnelStatus


def test_canonical_exclude_set_normalizes_aliases():
    assert canonical_exclude_set(["ПАО Сбербанк", "Sber", "Яндекс"]) == [
        "Сбербанк",
        "Яндекс",
    ]


def test_canonical_exclude_set_dedupes_and_keeps_unknown():
    assert canonical_exclude_set(["Yandex", "яндекс", "МояСтартапКомпания", "", None]) == [
        "Моястартапкомпания",
        "Яндекс",
    ]


def test_companies_registry_route_registered():
    from api.main import app

    paths = {ctx.path for ctx in iter_route_contexts(app.routes)}
    assert "/api/companies" in paths


def test_furthest_stage_label_base_is_viewed():
    assert furthest_stage_label([]) == FunnelStatus.VIEWED
    assert furthest_stage_label([None, ""]) == FunnelStatus.VIEWED


def test_furthest_stage_label_ignores_rejection():
    assert furthest_stage_label([FunnelStatus.SCREENING, FunnelStatus.REJECTED]) == (
        FunnelStatus.SCREENING
    )


def test_furthest_stage_label_takes_max():
    assert furthest_stage_label([FunnelStatus.APPLIED, FunnelStatus.OFFER]) == FunnelStatus.OFFER


def test_verdict_from_resume_lists_canonical():
    rows = [
        CompanyRow(company="Сбербанк", vacancy_count=2, avg_score=70.0),
        CompanyRow(company="Яндекс", vacancy_count=1, avg_score=80.0),
        CompanyRow(company="Авито", vacancy_count=3, avg_score=60.0),
    ]
    out = _with_verdict(
        rows,
        target_companies=["ПАО Сбербанк"],
        avoid_companies=["Yandex"],
    )
    by_name = {r.company: r.verdict for r in out}
    assert by_name == {"Сбербанк": "target", "Яндекс": "avoid", "Авито": "neutral"}


def test_verdict_target_wins_over_avoid():
    """Пересечение списков: target раньше avoid (как rules_from_search_lists)."""
    rows = [CompanyRow(company="Сбербанк", vacancy_count=1, avg_score=50.0)]
    out = _with_verdict(
        rows,
        target_companies=["Сбербанк"],
        avoid_companies=["Сбербанк"],
    )
    assert out[0].verdict == "target"


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
async def test_list_companies_aggregates_best_stage_and_sorts() -> None:
    from core.domains.opportunities.jobs import list_companies

    t1 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    t2 = datetime(2026, 7, 15, tzinfo=timezone.utc)
    t3 = datetime(2026, 7, 20, tzinfo=timezone.utc)
    db = _FakeDb(
        jobs=[
            {
                "id": 1,
                "company_canonical": "Яндекс",
                "status": FunnelStatus.APPLIED,
                "overall_score": 80,
                "created_at": t1,
            },
            {
                "id": 2,
                "company_canonical": "Яндекс",
                "status": FunnelStatus.VIEWED,
                "overall_score": 90,
                "created_at": t3,
            },
            {
                "id": 3,
                "company_canonical": "Авито",
                "status": FunnelStatus.VIEWED,
                "overall_score": 70,
                "created_at": t2,
            },
            {
                "id": 4,
                "company_canonical": "Сбербанк",
                "status": FunnelStatus.SCREENING,
                "overall_score": 60,
                "created_at": t1,
            },
            {
                "id": 5,
                "company_canonical": "Сбербанк",
                "status": FunnelStatus.VIEWED,
                "overall_score": 50,
                "created_at": t2,
            },
        ],
        stages=[
            {"job_id": 1, "stage": FunnelStatus.TECH},  # Яндекс дальше Технички
            {"job_id": 4, "stage": FunnelStatus.REJECTED},  # отказ не двигает шкалу
        ],
    )
    rows = await list_companies(account_id=1, db=db)
    assert [r.company for r in rows] == ["Яндекс", "Сбербанк", "Авито"]
    by_name = {r.company: r for r in rows}

    assert by_name["Яндекс"].vacancy_count == 2
    assert by_name["Яндекс"].avg_score == 85.0
    assert by_name["Яндекс"].best_stage == FunnelStatus.TECH
    assert by_name["Яндекс"].last_seen_at == t3

    assert by_name["Сбербанк"].vacancy_count == 2
    assert by_name["Сбербанк"].avg_score == 55.0
    assert by_name["Сбербанк"].best_stage == FunnelStatus.SCREENING
    assert by_name["Сбербанк"].last_seen_at == t2

    assert by_name["Авито"].vacancy_count == 1
    assert by_name["Авито"].best_stage == FunnelStatus.VIEWED


@pytest.mark.asyncio
async def test_list_companies_empty_without_jobs() -> None:
    from core.domains.opportunities.jobs import list_companies

    rows = await list_companies(account_id=1, db=_FakeDb(jobs=[], stages=[]))
    assert rows == []
