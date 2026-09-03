"""Что рынок реально предлагает под критерии владельца — формат работы + зарплата среди
СВОИХ заскоренных вакансий за последние `WINDOW_DAYS`. Независимый источник от `skip_insights`.

`market_supply` в сводке ситуации раньше пересказывал ровно те же `skip_*`-счётчики, что и
`skip_insights` — единственным входом про «рынок» были причины пропуска.
Здесь read-only агрегат по `jobs.work_format`/`jobs.salary`
среди заскоренных активных (не в skipped_vacancies) вакансий: что рынок предлагает тем,
кого ещё рассматриваем, а не что владелец уже отклонил.

Чистая `compute_market_supply` над списком строк (тестируется без БД) + тонкий
`get_market_supply_facts` (тянет PG). Мало вакансий в окне → честный `available=False`, не
натягиваем вывод на паре записей (зеркало `enough_data`-паттерна `salary_benchmark`/`funnel`).

D-06 добавляет сюда распределение (гистограмма вилок как отсортированный ряд net-середин —
бакеты считает фронт, `V-03 ValueAxis`, как и остальная геометрия графиков), четверти и зону
цели из резюме (`SearchProfile.salary_anchor_base`) — тот же корпус, что уже кормит
`salary_median_net`, просто не сжатый до одного числа.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from statistics import median, quantiles

from pydantic import BaseModel, Field

from core.domains.market.market import MarketBucket, _salary_net_mid
from core.domains.market.relevance import _score_of
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30
MIN_SAMPLES = 3  # честный empty при малой выборке

# Приоритет удалёнка > гибрид > офис — вакансия с "удалённо, гибрид" в тексте считается один раз,
# не размножается по корзинам (иначе проценты по корзинам не сходятся к 100%).
_WORK_FORMAT_BUCKETS: tuple[tuple[str, str], ...] = (
    ("remote", "удалённо"),
    ("hybrid", "гибрид"),
    ("office", "офис"),
)


class MarketSupplyFacts(BaseModel):
    """Что рынок реально предлагает среди заскоренных вакансий за `window_days` — не skip."""

    available: bool = False
    window_days: int = WINDOW_DAYS
    measured: int = 0
    work_formats: list[MarketBucket] = Field(default_factory=list)
    salary_measured: int = 0
    salary_median_net: int | None = None
    salary_min_net: int | None = None
    salary_max_net: int | None = None
    salary_p25_net: int | None = None
    salary_p75_net: int | None = None
    # Отсортированный ряд net-середин — сырьё для гистограммы; бакеты — забота фронта.
    salary_points: list[int] = Field(default_factory=list)
    # Зона цели из резюме (`SearchProfile.salary_anchor_base`) — не зависит от того, набралась ли
    # рыночная выборка, поэтому не гасится вместе с остальными salary_* при малом n.
    target_min_net: int | None = None
    target_max_net: int | None = None


def _classify_work_format(text: str | None) -> str | None:
    """Текст `jobs.work_format` (hh `workFormats`, `parsing.hh_search`) → 1 из 3 корзин."""
    t = (text or "").lower()
    if "удал" in t:
        return "remote"
    if "гибрид" in t:
        return "hybrid"
    return "office" if t.strip() else None


def compute_market_supply(
    rows: list[tuple[str | None, dict | None, int | None, dict | None, datetime | None]],
    *,
    now: datetime | None = None,
    window_days: int = WINDOW_DAYS,
    min_samples: int = MIN_SAMPLES,
    target_min_net: int | None = None,
    target_max_net: int | None = None,
    tracks: Sequence[str | None] | None = None,
) -> MarketSupplyFacts:
    """rows: (work_format, salary-jsonb, overall_score, score-jsonb, scored_at). Чистая — без БД.

    Заскоренной считаем вакансию с читаемым баллом (`relevance._score_of`); окно — последние
    `window_days` по `scored_at`. `target_min_net`/`target_max_net` — зона цели из резюме,
    прокинута снаружи (профиль читает только тонкая обёртка `get_market_supply_facts`).
    `tracks` той же длины, что `rows`: второй трек не кормит рублёвую гистограмму (Э3.3).
    """
    cutoff = (now or datetime.now(UTC)) - timedelta(days=window_days)
    recent: list[tuple[str | None, dict]] = []
    for i, (work_format, salary_raw, overall, score_raw, scored_at) in enumerate(rows):
        sd = score_raw if isinstance(score_raw, dict) else {}
        if _score_of(overall, sd) is None:
            continue
        at = scored_at
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if at is None or at < cutoff:
            continue
        track = (tracks[i] if tracks is not None and i < len(tracks) else None) or "primary"
        if track == "second_job":
            salary: dict = {}
        else:
            raw = salary_raw if isinstance(salary_raw, dict) else sd.get("salary")
            salary = raw if isinstance(raw, dict) else {}
        recent.append((work_format, salary))

    n = len(recent)
    if n < min_samples:
        return MarketSupplyFacts(
            available=False,
            window_days=window_days,
            measured=n,
            target_min_net=target_min_net,
            target_max_net=target_max_net,
        )

    fmt_counter: Counter[str] = Counter()
    for work_format, _ in recent:
        bucket = _classify_work_format(work_format)
        if bucket:
            fmt_counter[bucket] += 1
    fmt_total = sum(fmt_counter.values())
    work_formats = [
        MarketBucket(
            label=label,
            count=fmt_counter[key],
            pct=round(100 * fmt_counter[key] / fmt_total, 1) if fmt_total else 0.0,
        )
        for key, label in _WORK_FORMAT_BUCKETS
        if fmt_counter.get(key)
    ]

    net_mids = [v for v in (_salary_net_mid(salary) for _, salary in recent) if v is not None]
    salary_measured = len(net_mids)
    enough_salary = salary_measured >= min_samples

    p25 = p75 = None
    if enough_salary:
        q1, _q2, q3 = quantiles(net_mids, n=4)
        p25, p75 = int(round(q1)), int(round(q3))

    return MarketSupplyFacts(
        available=True,
        window_days=window_days,
        measured=n,
        work_formats=work_formats,
        salary_measured=salary_measured,
        salary_median_net=int(median(net_mids)) if enough_salary else None,
        salary_min_net=min(net_mids) if enough_salary else None,
        salary_max_net=max(net_mids) if enough_salary else None,
        salary_p25_net=p25,
        salary_p75_net=p75,
        salary_points=sorted(net_mids) if enough_salary else [],
        target_min_net=target_min_net,
        target_max_net=target_max_net,
    )


async def get_market_supply_facts(
    *, account_id: int, db: Executor | None = None
) -> MarketSupplyFacts:
    """Собрать агрегат аккаунта из Postgres. Read-only, без LLM. Без skipped — калибровка, не отказы."""
    db = db or get_pool()
    from core.domains.opportunities.jobs import SQL_JOB_NOT_SKIPPED
    from core.domains.profile.profile import load_candidate_profile_enriched
    from core.domains.profile.structured_store import read_resume_data_for_account

    target_min_net: int | None = None
    target_max_net: int | None = None
    try:
        resume_data = await read_resume_data_for_account(account_id, db=db)
        profile = await load_candidate_profile_enriched(
            account_id=account_id, data=resume_data, db=db
        )
        anchor = profile.salary_anchor_base()
        if anchor is not None:
            target_min_net, target_max_net = anchor
    except Exception as exc:  # noqa: BLE001 — нет резюме → зона цели пустая, остальное не ломаем
        logger.debug("market-supply: профиль недоступен, зона цели пустая: %s", exc)

    try:
        rows = await db.fetch(
            "select work_format, salary, overall_score, score, scored_at, track from jobs "
            f"where account_id = $1 and {SQL_JOB_NOT_SKIPPED}",
            account_id,
        )
    except Exception:  # noqa: BLE001 — нет колонки track на старой схеме
        rows = await db.fetch(
            "select work_format, salary, overall_score, score, scored_at from jobs "
            f"where account_id = $1 and {SQL_JOB_NOT_SKIPPED}",
            account_id,
        )
    tuples = [
        (r["work_format"], r["salary"], r["overall_score"], r["score"], r["scored_at"])
        for r in rows
    ]
    tracks = [dict(r).get("track") for r in rows]
    return compute_market_supply(
        tuples,
        target_min_net=target_min_net,
        target_max_net=target_max_net,
        tracks=tracks,
    )


__all__ = [
    "MIN_SAMPLES",
    "WINDOW_DAYS",
    "MarketSupplyFacts",
    "compute_market_supply",
    "get_market_supply_facts",
]
