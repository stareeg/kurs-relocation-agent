"""Реестр компаний для доски «Рынок → Компании».

Кросс-доменный сценарий: агрегаты из `opportunities.jobs`, вердикт —
`profile` (target/avoid из резюме). Раньше склейка жила в
`api/routers/opportunities/companies.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from core.domains.opportunities.jobs import CompanyRow, canonical_exclude_set

logger = logging.getLogger(__name__)

CompanyVerdict = Literal["target", "avoid", "neutral"]


class CompanyRegistryRow(BaseModel):
    """Строка реестра: агрегат вакансий + вердикт из резюме."""

    company: str
    vacancy_count: int
    avg_score: float
    best_stage: str | None = None
    last_seen_at: datetime | None = None
    verdict: CompanyVerdict = "neutral"


def _verdict_for(
    company: str,
    *,
    targets: set[str],
    avoids: set[str],
) -> CompanyVerdict:
    """Вердикт по канону: target побеждает avoid при пересечении (как в rules_from_search_lists)."""
    if company in targets:
        return "target"
    if company in avoids:
        return "avoid"
    return "neutral"


def _with_verdict(
    rows: list[CompanyRow],
    *,
    target_companies: list[str] | None,
    avoid_companies: list[str] | None,
) -> list[CompanyRegistryRow]:
    targets = set(canonical_exclude_set(target_companies or []))
    avoids = set(canonical_exclude_set(avoid_companies or []))
    return [
        CompanyRegistryRow(
            company=r.company,
            vacancy_count=r.vacancy_count,
            avg_score=r.avg_score,
            best_stage=r.best_stage,
            last_seen_at=r.last_seen_at,
            verdict=_verdict_for(r.company, targets=targets, avoids=avoids),
        )
        for r in rows
    ]


async def list_registry(*, account_id: int) -> list[CompanyRegistryRow]:
    """Полный реестр компаний: агрегаты + verdict из target/avoid резюме аккаунта запроса."""
    from core.domains.opportunities.jobs import list_companies
    from core.domains.profile.structured_store import read_resume_data_for_account

    try:
        rows = list(await list_companies(account_id=account_id))
    except Exception as exc:  # noqa: BLE001 — нет PG → пустой реестр, не 500
        logger.debug("company registry: Postgres недоступен: %s", exc)
        return []

    try:
        data = await read_resume_data_for_account(account_id)
        sc = data.search_criteria
        target = list(sc.target_companies or [])
        avoid = list(sc.avoid_companies or [])
    except Exception as exc:  # noqa: BLE001 — битое резюме → все neutral
        logger.debug("company registry: резюме недоступно: %s", exc)
        target, avoid = [], []

    return _with_verdict(rows, target_companies=target, avoid_companies=avoid)


__all__ = [
    "CompanyRegistryRow",
    "CompanyVerdict",
    "list_registry",
]
