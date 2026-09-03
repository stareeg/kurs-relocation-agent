"""Корпус выборки для навыков.

`gap.load_corpus()` берёт всё непропущенное — 71 вакансия на живой базе, из них 16 со скором
ниже 40 и 14 в статусе «Отказ». Для «чему мне стоит поучиться» это неверный
корпус: считать нужно по вакансиям, которые владелец реально хочет, а не по всему, что не
скрыл руками.

Правило выборки — детерминированное, без LLM: не в `skipped_vacancies` И (`overall_score` ≥
порога ИЛИ статус из `ENGAGED_FUNNEL_STATUSES` ИЛИ компания из `target_companies` резюме).
Порог настраивается в `app_settings` (`skills_selection_min_score`, дефолт 55), а не в коде —
владелец может подвинуть его без правки Python.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.domains.opportunities.jobs import SQL_JOB_NOT_SKIPPED, company_canonical_for
from core.domains.profile.model import ResumeData
from core.kernel.schemas.funnel import ENGAGED_FUNNEL_STATUSES
from core.platform.db.pool import Executor, get_pool
from core.platform.repo.settings import get_setting

DEFAULT_MIN_SCORE = 55
SETTING_KEY = "skills_selection_min_score"


class SelectionVacancy(BaseModel):
    """Одна вакансия выборки — вход для извлечения требований."""

    vacancy_id: str
    title: str
    company: str
    text: str
    score: int | None
    status: str | None


def _target_company_canons(data: ResumeData) -> list[str]:
    """Каноны `target_companies` резюме аккаунта запроса — битое/пустое резюме не должно
    ронять выборку."""
    try:
        names = data.search_criteria.target_companies
    except Exception:  # noqa: BLE001 — выборка не должна падать из-за резюме
        return []
    canons = {canon for name in names or () if (canon := company_canonical_for(name))}
    return sorted(canons)


async def load_min_score(*, account_id: int, db: Executor | None = None) -> int:
    """Порог `overall_score` выборки — из настроек аккаунта запроса, дефолт `DEFAULT_MIN_SCORE`."""
    value = await get_setting(SETTING_KEY, default=DEFAULT_MIN_SCORE, account_id=account_id, db=db)
    try:
        return int(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SCORE


def build_selection_sql(
    min_score: int, target_canons: list[str], *, account_id: int
) -> tuple[str, list[object]]:
    """SQL + параметры правила выборки (Решение 3) — вынесено из `load_selection_corpus`
    для юнит-теста без БД."""
    clauses = [
        "account_id = $1",
        SQL_JOB_NOT_SKIPPED,
        "vacancy_text is not null",
        "length(vacancy_text) > 150",
    ]
    engaged = ", ".join(f"'{s}'" for s in sorted(ENGAGED_FUNNEL_STATUSES))
    params: list[object] = [account_id, min_score]
    rule = f"(overall_score >= $2 or status in ({engaged})"
    if target_canons:
        rule += " or company_canonical = any($3::text[])"
        params.append(target_canons)
    rule += ")"
    clauses.append(rule)
    sql = (
        "select vacancy_id, coalesce(title,'') t, coalesce(company,'') c, "
        "coalesce(vacancy_text,'') x, overall_score, status "
        f"from jobs where {' and '.join(clauses)}"
    )
    return sql, params


async def _load_corpus_with_threshold(
    *, account_id: int, data: ResumeData, db: Executor | None
) -> tuple[list[SelectionVacancy], int]:
    if db is None:
        db = get_pool()

    min_score = await load_min_score(account_id=account_id, db=db)
    sql, params = build_selection_sql(
        min_score, _target_company_canons(data), account_id=account_id
    )
    rows = await db.fetch(sql, *params)  # type: ignore[attr-defined]
    corpus = [
        SelectionVacancy(
            vacancy_id=r["vacancy_id"],
            title=r["t"],
            company=r["c"],
            text=r["x"],
            score=r["overall_score"],
            status=r["status"],
        )
        for r in rows
    ]
    return corpus, min_score


async def load_selection_corpus(
    *, account_id: int, data: ResumeData, db: Executor | None = None
) -> list[SelectionVacancy]:
    """Вакансии выборки аккаунта запроса (Решение 3): не пропущено И (скор ≥ порога ИЛИ в
    работе ИЛИ целевая компания)."""
    corpus, _ = await _load_corpus_with_threshold(account_id=account_id, data=data, db=db)
    return corpus


def plural_vacancies(n: int) -> str:
    """Русское склонение «вакансия/вакансии/вакансий» по числу — переиспользуется в E-02 для
    точного `stale_reason` («+12 новых вакансий»), не только в `describe_selection`."""
    n_abs = abs(n) % 100
    last = n_abs % 10
    if 11 <= n_abs <= 14:
        return "вакансий"
    if last == 1:
        return "вакансия"
    if 2 <= last <= 4:
        return "вакансии"
    return "вакансий"


async def describe_selection(
    *, account_id: int, data: ResumeData, db: Executor | None = None
) -> str:
    """Правило выборки словами для UI: «43 вакансии: скор ≥ 55 или в работе, без пропущенных»."""
    corpus, min_score = await _load_corpus_with_threshold(account_id=account_id, data=data, db=db)
    n = len(corpus)
    return f"{n} {plural_vacancies(n)}: скор ≥ {min_score} или в работе, без пропущенных"


__all__ = [
    "DEFAULT_MIN_SCORE",
    "SETTING_KEY",
    "SelectionVacancy",
    "build_selection_sql",
    "describe_selection",
    "load_min_score",
    "load_selection_corpus",
    "plural_vacancies",
]
