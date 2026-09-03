"""Рыночный бенчмарк зарплат по своему корпусу.

Отвечает на «сколько сейчас реально предлагают под мой грейд» — для уверенности на торге по
деньгам. Два источника, с честным провенансом, не смешиваются в одно число:

- **Наблюдения** — `salary_calibration_samples`: реальные названные числа (HR-факты,
  офферы, посты с конкретной вилкой), не оценка модели.
- **Объявленные вилки JD** — свой корпус `jobs`: `ScoreResult.salary.estimated_*` (то, что скорер
  прочитал/оценил из текста вакансии) — менее надёжно, hh-вилка не обязательна и часто занижена.

Срезы по грейду (`grade_match.level`/сэмпл-грейд → senior_plus|mid|junior, как в
`salary_aggregate._grade_bucket`). Зашитый срез «LLM/agentic» убран: рынок универсален, а не
под один стек. Малое n не рисует вывод — цифра гасится, честно показывается только `n`.

Чистая `compute_salary_benchmark` над списками (тестируется без БД) + тонкий
`get_salary_benchmark_report`, тянущий Postgres.

D-06 добавляет сюда же свои живые офферы (`compute_live_offer_points`): та же точка сравнения,
что и рыночный бенчмарк выше, только со своими фактическими числами, а не чужими. Приводятся к
общему основанию — месяц, на руки (`core.kernel.money.to_monthly` + `to_net`), тем же расчётом,
что кормит корпус калибровки (`salary_corpus.feed_offer_sample`) — не два разных числа для одного
оффера в разных местах продукта.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from statistics import median

from pydantic import BaseModel, Field

from core.domains.market.salary_calib import CalibSample, fetch_relevant_samples
from core.domains.market.salary_calibration.salary_aggregate import (
    MIN_SEGMENT_SAMPLES,
    _grade_bucket,
    dedupe_samples,
    filter_outliers,
)
from core.domains.offers.store import Offer, load_active_offers
from core.kernel.money import gross_to_net, to_monthly, to_net
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

# Живые офферы — тот же горизонт свежести, что берёт `situation._load_offers` для сводки рынка.
LIVE_OFFER_MAX_AGE_DAYS = 180

# Грейды в этом порядке рендерятся сегменты.
GRADE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("senior_plus", "Senior+/Techlead/Lead"),
    ("mid", "Middle"),
    ("junior", "Junior"),
)

# Совместимость API/UI: один бакет на грейд (раньше был llm|other).
_STACK_ALL = ("all", "Все")


class SalaryBenchmarkPoint(BaseModel):
    """Медианная net-вилка сегмента из одного источника. Мало данных → цифры гасятся, n виден."""

    n: int = 0
    enough_data: bool = False
    median_min_net: int | None = None
    median_max_net: int | None = None
    median_mid_net: int | None = None


class SalaryBenchmarkSegment(BaseModel):
    """Один срез по грейду: наблюдения (факт) и вилки JD (менее надёжно) — раздельно."""

    grade: str
    grade_label: str
    stack: str = _STACK_ALL[0]
    stack_label: str = _STACK_ALL[1]
    observations: SalaryBenchmarkPoint = Field(default_factory=SalaryBenchmarkPoint)
    declared: SalaryBenchmarkPoint = Field(default_factory=SalaryBenchmarkPoint)


class SalaryBenchmarkReport(BaseModel):
    """Ответ `GET /api/analytics/salary-benchmark`. `available=false` — нет ни одного сигнала."""

    available: bool = False
    min_n: int = MIN_SEGMENT_SAMPLES
    segments: list[SalaryBenchmarkSegment] = Field(default_factory=list)


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _job_grade_bucket(score: dict) -> str | None:
    """Корзина бенчмарка из `grade_match.level`.

    Легаси jsonb держал абсолютные senior_plus|mid|junior. Новая шкала относительная
    (match/above/…) - при цели Senior+ мапим match/above → senior_plus и т.д.
    """
    gm = score.get("grade_match")
    level = gm.get("level") if isinstance(gm, dict) else None
    if not isinstance(level, str):
        return None
    key = level.strip().lower()
    if key in ("senior_plus", "mid", "junior"):
        return key
    if key in ("match", "above"):
        return "senior_plus"
    if key == "slightly_below":
        return "mid"
    if key == "far_below":
        return "junior"
    return None


def _job_declared_net(salary: dict) -> tuple[int, int] | None:
    """Net-вилка из оценки скорера (`estimated_min/max`, gross→net). None — нет читаемой оценки."""
    lo = salary.get("estimated_min")
    hi = salary.get("estimated_max")
    if not (isinstance(lo, int | float) and lo > 0):
        return None
    hi = hi if isinstance(hi, int | float) and hi > 0 else lo
    net_lo, net_hi = gross_to_net(int(lo)), gross_to_net(int(hi))
    if net_lo is None or net_hi is None:
        return None
    return (net_lo, net_hi) if net_lo <= net_hi else (net_hi, net_lo)


def _point(pairs: list[tuple[int, int]], min_n: int) -> SalaryBenchmarkPoint:
    n = len(pairs)
    if n == 0:
        return SalaryBenchmarkPoint()
    enough = n >= min_n
    return SalaryBenchmarkPoint(
        n=n,
        enough_data=enough,
        median_min_net=int(median(p[0] for p in pairs)) if enough else None,
        median_max_net=int(median(p[1] for p in pairs)) if enough else None,
        median_mid_net=int(median((p[0] + p[1]) / 2 for p in pairs)) if enough else None,
    )


def compute_salary_benchmark(
    samples: list[CalibSample],
    job_rows: list[tuple[dict, dict]],
    *,
    min_n: int = MIN_SEGMENT_SAMPLES,
) -> SalaryBenchmarkReport:
    """Собрать сегменты по грейду из наблюдений + объявленных вилок JD. Чистая — без БД.

    `samples` — отфильтрованные по `is_relevant`/`salary_min_net` (как `fetch_relevant_samples`);
    здесь дополнительно дедуп + отсев выбросов (тот же паттерн, что `compute_segment_prior`).
    `job_rows` — пары (score-jsonb, salary-jsonb) корпуса вакансий.
    """
    clean_samples = filter_outliers(dedupe_samples([s for s in samples if s.salary_min_net]))
    obs_pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for s in clean_samples:
        bucket = _grade_bucket(s.grade)
        if bucket is None:
            continue
        lo = int(s.salary_min_net)  # type: ignore[arg-type]
        hi = int(s.salary_max_net or s.salary_min_net)  # type: ignore[arg-type]
        pair = (lo, hi) if lo <= hi else (hi, lo)
        obs_pairs[bucket].append(pair)

    decl_pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for score, salary_raw in job_rows:
        sd = _as_dict(score)
        grade = _job_grade_bucket(sd)
        if grade is None:
            continue
        salary = _as_dict(salary_raw) or _as_dict(sd.get("salary"))
        pair = _job_declared_net(salary)
        if pair is None:
            continue
        decl_pairs[grade].append(pair)

    stack_key, stack_label = _STACK_ALL
    segments: list[SalaryBenchmarkSegment] = []
    for grade_key, grade_label in GRADE_BUCKETS:
        obs = _point(obs_pairs.get(grade_key, []), min_n)
        decl = _point(decl_pairs.get(grade_key, []), min_n)
        if obs.n == 0 and decl.n == 0:
            continue
        segments.append(
            SalaryBenchmarkSegment(
                grade=grade_key,
                grade_label=grade_label,
                stack=stack_key,
                stack_label=stack_label,
                observations=obs,
                declared=decl,
            )
        )

    return SalaryBenchmarkReport(available=bool(segments), min_n=min_n, segments=segments)


async def get_salary_benchmark_report(
    *, account_id: int, db: Executor | None = None
) -> SalaryBenchmarkReport:
    """Собрать бенчмарк аккаунта из Postgres. Read-only, без LLM.

    M5 (plans/multitenancy_gaps_2026_08_06.md §3.6): `jobs` раньше читался без фильтра вообще —
    «свой корпус» на деле был корпусом всех аккаунтов системы.
    Второй трек и не-рублёвые вилки в рублёвую сетку не входят: без FX смешать 250 000 ₽ и
    $45/час — бессмысленная медиана (Э3.3).
    """
    db = db or get_pool()
    samples = await fetch_relevant_samples(account_id=account_id, db=db)
    try:
        job_rows = await db.fetch(
            "select score, salary, track, work_terms from jobs where account_id = $1",
            account_id,
        )
    except Exception:  # noqa: BLE001 — нет колонок track/work_terms на старой схеме
        job_rows = await db.fetch(
            "select score, salary from jobs where account_id = $1", account_id
        )
    pairs: list[tuple[dict, dict]] = []
    for r in job_rows:
        row = dict(r)
        if str(row.get("track") or "primary") == "second_job":
            continue
        wt = row.get("work_terms") or {}
        cur = str(wt.get("currency") or "").strip().upper() if isinstance(wt, dict) else ""
        if cur and cur != "RUB":
            continue
        pairs.append((_as_dict(row.get("score")), _as_dict(row.get("salary"))))
    return compute_salary_benchmark(samples, pairs)


# Порог «мало наблюдений» — тот же, что RATE_CORPUS_MIN оси ставки (Э2.5). Без FX:
# каждая валюта — своя шкала, рубли сюда не входят.
FX_RATE_MIN_N = 8
_FX_PERIODS: tuple[str, ...] = ("hour", "day", "month", "year")


class FxRateBucket(BaseModel):
    """Медианная ставка в одной валюте и периоде. Мало данных → цифра гасится, n виден."""

    currency: str
    rate_period: str
    n: int = 0
    enough_data: bool = False
    median_mid: int | None = None


class FxRateScale(BaseModel):
    """Валютные ставки второго трека. Без конвертации, каждая валюта — своя шкала."""

    available: bool = False
    min_n: int = FX_RATE_MIN_N
    buckets: list[FxRateBucket] = Field(default_factory=list)


def _rate_mid(terms: dict) -> int | None:
    lo, hi = terms.get("rate_min"), terms.get("rate_max")
    nums = [int(v) for v in (lo, hi) if isinstance(v, (int, float)) and v > 0]
    if not nums:
        return None
    return (min(nums) + max(nums)) // 2


def compute_fx_rate_scale(
    terms_rows: list[dict],
    *,
    min_n: int = FX_RATE_MIN_N,
) -> FxRateScale:
    """Собрать валютные ставки из work_terms. Чистая — без БД.

    RUB и пустая валюта отбрасываются. Период `unknown` — тоже. Мало наблюдений
    в бакете → `enough_data=False` и `median_mid=None`, не выдуманная медиана.
    """
    grouped: dict[tuple[str, str], list[int]] = defaultdict(list)
    for raw in terms_rows:
        terms = raw if isinstance(raw, dict) else {}
        cur = str(terms.get("currency") or "").strip().upper()
        period = str(terms.get("rate_period") or "").strip()
        if not cur or cur == "RUB" or period not in _FX_PERIODS:
            continue
        mid = _rate_mid(terms)
        if mid is None:
            continue
        grouped[(cur, period)].append(mid)

    buckets: list[FxRateBucket] = []
    for (currency, period), mids in sorted(grouped.items()):
        n = len(mids)
        enough = n >= min_n
        buckets.append(
            FxRateBucket(
                currency=currency,
                rate_period=period,
                n=n,
                enough_data=enough,
                median_mid=int(median(mids)) if enough else None,
            )
        )
    return FxRateScale(available=bool(buckets), min_n=min_n, buckets=buckets)


async def get_fx_rate_scale(*, account_id: int, db: Executor | None = None) -> FxRateScale:
    """Валютные ставки второго трека аккаунта. Read-only, без LLM."""
    db = db or get_pool()
    try:
        rows = await db.fetch(
            "select work_terms from jobs "
            "where account_id = $1 and coalesce(track, 'primary') = 'second_job' "
            "and work_terms is not null",
            account_id,
        )
    except Exception as exc:  # noqa: BLE001 — нет колонок/PG → честный empty
        logger.debug("fx rate scale недоступен: %s", exc)
        return FxRateScale()
    terms_rows = [r["work_terms"] or {} for r in rows]
    return compute_fx_rate_scale([t for t in terms_rows if isinstance(t, dict)])


class LiveOfferPoint(BaseModel):
    """Один свой оффер на оси денег: оклад, приведённый к месяцу и «на руки»."""

    company: str
    position: str = ""
    monthly_net: int


def compute_live_offer_points(offers: list[Offer]) -> list[LiveOfferPoint]:
    """Свои офферы → точки на оси денег. Чистая — тестируется без БД.

    Основание — месяц/net, как у рыночной вилки (`_salary_net_mid`,
    `market_supply.compute_market_supply`), иначе офферы и рынок не сопоставимы на одной оси.
    Не-рублёвые офферы пропускаем: в продукте нет FX-конвертации, смешать валюты на одной шкале —
    соврать про сопоставимость (не «честный empty», а неверное число).
    """
    points: list[LiveOfferPoint] = []
    for offer in offers:
        if not offer.base_salary or offer.base_salary <= 0:
            continue
        if (offer.base_salary_currency or "RUB").strip().upper() != "RUB":
            continue
        monthly = to_monthly(offer.base_salary, offer.base_salary_period)
        monthly_net = to_net(monthly, tax_basis=offer.base_salary_tax_basis)
        if monthly_net is None:
            continue
        points.append(
            LiveOfferPoint(
                company=(offer.company or "").strip() or "Без названия",
                position=(offer.position or "").strip(),
                monthly_net=monthly_net,
            )
        )
    return points


async def get_live_offer_points(
    *, account_id: int, db: Executor | None = None
) -> list[LiveOfferPoint]:
    """Живые офферы аккаунта из Postgres. Read-only, без LLM."""
    pool = db or get_pool()
    offers = await load_active_offers(
        max_age_days=LIVE_OFFER_MAX_AGE_DAYS, account_id=account_id, db=pool
    )
    return compute_live_offer_points(offers)


__all__ = [
    "FX_RATE_MIN_N",
    "GRADE_BUCKETS",
    "LIVE_OFFER_MAX_AGE_DAYS",
    "FxRateBucket",
    "FxRateScale",
    "LiveOfferPoint",
    "SalaryBenchmarkPoint",
    "SalaryBenchmarkSegment",
    "SalaryBenchmarkReport",
    "compute_fx_rate_scale",
    "compute_live_offer_points",
    "compute_salary_benchmark",
    "get_fx_rate_scale",
    "get_live_offer_points",
    "get_salary_benchmark_report",
]
