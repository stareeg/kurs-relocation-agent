"""LLM-сводка ситуации «Рынок» (grid + source funnel + недельное ретро воронки).

Reasoning-модель по готовым агрегатам (`gather_situation_facts`) → structured `SituationNarrative`.
Кэш — `core.domains.market.situation_store` (генерация только по кнопке).

UX5-20: раньше «Сводка ситуации» и «Ретро воронки» были двумя независимыми бэкендами —
разные факт-сборщики, разные промпты, разные схемы вывода. Слиты в один вызов: одна кнопка на
фронте → один reasoning-запрос → одна структурная схема. Факты периода (воронка/скипы/фидбек HR за
последние `RETRO_PERIOD_DAYS` дней против предыдущего периода той же длины) — чистая агрегация без
LLM, подмешиваются в `SituationFacts.retro` и в user-промпт как отдельная секция ПЕРИОД.

B-09: all-time SKIP_BREAKDOWN и MARKET_SUPPLY из входа убраны (потребители в narrative удалены в
B-07); предложение рынка — отдельная ручка money. Источники (hh/getmatch/habr/tg) оставлены для
адресных actions.

D-08: `SituationNarrative` урезана до двух полей —
вывод и шаги с адресатом. Всё, что раньше модель формулировала текстом (диагноз воронки, куда
бить, оценка сроков/вилки), теперь нарисовано кодом на самом экране; модель делает только то,
что код не умеет — расставляет приоритет и называет конкретные объекты. Split
diagnosis/actions снят вместе с полями, которые его требовали: одна схема из двух полей
не упирается в лимит сложности Anthropic, второй параллельный вызов не нужен.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.config import CoreSettings, get_settings
from core.domains.market.market_grid import MarketGrid, format_market_grid_json_for_llm
from core.domains.market.search_metrics import SearchMetrics, get_search_metrics
from core.domains.offers.store import Offer, load_active_offers
from core.domains.opportunities.jobs import Job, list_jobs
from core.domains.opportunities.skip_reasons import (
    SELF_SKIP_REASONS,
    canonical_skip_reason,
)
from core.domains.pipeline.analytics import FUNNEL_ORDER, FunnelAnalytics, compute_funnel_at
from core.domains.profile.model import ResumeData
from core.domains.profile.profile import SearchProfile, load_search_profile
from core.domains.profile.structured_store import read_default_resume_data
from core.kernel import ports
from core.kernel.errors import LlmError
from core.platform.db.pool import Executor, get_pool
from core.platform.observability import event

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 7
LEGACY_CACHE_NOTE = "Сводка в старом формате. Нажми «Разобрать ситуацию» для актуальной версии."

# UX5-20: период ретро зафиксирован (раньше был тумблер 7д/14д на фронте) — тумблер убран вместе
# со слиянием, отдельное время обновления ретро больше не нужно.
RETRO_PERIOD_DAYS = 7
_MAX_QUOTES = 15
_MAX_STEPS = 3

# UX2-10.2: потолок на сбор фактов — сверх per-query postgres_command_timeout_s, отдельный
# предохранитель на всю цепочку gather_situation_facts, чтобы зависший пул/запрос падал с понятной
# ошибкой, а не крутил спиннер бесконечно. UX5-20: запросы (включая gather_retro_facts) идут через
# asyncio.gather параллельно, не последовательно — так что таймаут ограничивает самый долгий запрос,
# не их сумму.
_FACTS_TIMEOUT_S = 45.0

_MAX_TEXT_LEN = 160
_MAX_CONCLUSION_LEN = 140


class SituationJobBrief(BaseModel):
    title: str = ""
    company: str = ""
    score: int = 0
    recommendation: str | None = None
    status: str | None = None
    source: str | None = None


class SituationCompanyBrief(BaseModel):
    company: str = ""
    best_score: int = 0
    jobs_count: int = 0


class SituationOfferBrief(BaseModel):
    """Активный оффер как вход сводки «Рынок» - синица в руке против журавля в поиске."""

    company: str = ""
    position: str = ""
    base_salary: int | None = None
    base_salary_currency: str = "RUB"
    base_salary_period: str = "month"
    work_format: str = "unknown"
    office_days_per_week: int | None = None
    status: str = "active"
    deadline: datetime | None = None
    days_until_deadline: int | None = None


class PeriodStageDelta(BaseModel):
    """Сколько вакансий ВПЕРВЫЕ дошли до ступени за период vs за предыдущий период той же длины."""

    stage: str
    now: int = 0
    prev: int = 0


class PeriodReasonCount(BaseModel):
    """Причина ручного пропуска (SELF_SKIP_REASONS) — счёт за период vs предыдущий период."""

    reason: str
    now: int = 0
    prev: int = 0


class HrRejectionQuote(BaseModel):
    """Фидбек рекрутёра по отказу на конкретном этапе — сырая цитата, не пересказ."""

    stage: str
    feedback: str
    created_at: datetime


class RetroFacts(BaseModel):
    """Факты периода ретро воронки (RD-18/UX5-20) - период vs предыдущий период той же длины.

    Без LLM, чистая агрегация. Подмешивается в `SituationFacts.retro`.
    """

    period_days: int = RETRO_PERIOD_DAYS
    funnel: list[PeriodStageDelta] = Field(default_factory=list)
    skip_reasons: list[PeriodReasonCount] = Field(default_factory=list)
    hr_rejection_quotes: list[HrRejectionQuote] = Field(default_factory=list)
    score_revisions_now: int = 0
    score_revisions_prev: int = 0
    total_jobs: int = 0


class SituationFacts(BaseModel):
    """Фактический вход сводки: grid + search + top jobs/companies + факты периода (ретро).

    B-09: market_supply / all-time skip_breakdown больше не собираем — ушли вместе с
    удалёнными полями narrative; предложение рынка отдаёт `GET /api/analytics/money`.
    """

    grid: MarketGrid = Field(default_factory=MarketGrid)
    search: SearchMetrics = Field(default_factory=SearchMetrics)
    top_jobs: list[SituationJobBrief] = Field(default_factory=list)
    top_companies: list[SituationCompanyBrief] = Field(default_factory=list)
    active_offers: list[SituationOfferBrief] = Field(default_factory=list)
    retro: RetroFacts = Field(default_factory=RetroFacts)
    days_active: int | None = None
    horizon_days: int = 60
    # ST-03 (узкий срез): режим поиска владельца ("Активно ищу"/"Рассматриваю") — только контекст
    # для тона совета в ТАЙМИНГ, не входит в веса/формулы MARKET_GRID_JSON или Шанса офферов.
    search_mode_label: str = ""
    # Э3.3: включённые треки (основная / вторая работа) — рядом с режимом, не в формулы сетки.
    search_track_label: str = ""


# Закрытый список разделов-адресатов (план §5): свободный текст в адресате не принимается,
# валидация — здесь, в схеме, а не в промпте.
SituationTargetSection = Literal["jobs", "resume", "screenings", "tech", "offers"]


class SituationTarget(BaseModel):
    """Адресат шага: раздел приложения + параметры фильтра — превращает совет в кнопку.

    Резолвинг в реальный маршрут и валидация набора параметров — `market/links.ts` на
    фронте; здесь схема лишь ограничивает раздел закрытым перечнем. Модель выбирает `params`
    только из объектов, переданных ей на вход (компании/вакансии из фактов) — не из воздуха.
    """

    section: SituationTargetSection | None = Field(
        default=None,
        description="раздел из закрытого списка; нет подходящего адресата — null",
    )
    params: dict[str, str] = Field(
        default_factory=dict,
        description="параметры фильтра раздела, только из переданных модели объектов",
    )


class SituationStep(BaseModel):
    """Один шаг «что сделать»: текст + адресат."""

    text: str = Field(max_length=160, description="одна строка: что сделать, без чисел")
    target: SituationTarget = Field(default_factory=SituationTarget)


class SituationNarrative(BaseModel):
    """Структурный вывод reasoning-модели — 2 поля.

    До D-08 было 6 текстовых полей/оценок (summary/funnel_diagnosis/best_targets/actions/
    likely_search_days/likely_salary) - диагностика и оценки теперь нарисованы кодом на самом
    экране «Рынок» (план §5), модель добавляет только то, чего код не умеет.
    """

    conclusion: str = Field(
        default="",
        max_length=140,
        description="одна фраза, до 140 символов, без чисел",
    )
    steps: list[SituationStep] = Field(
        default_factory=list,
        description="1-3 шага; у каждого текст и адресат",
    )


def _trim_steps(items: list[SituationStep]) -> list[SituationStep]:
    out: list[SituationStep] = []
    for it in items:
        text = it.text.strip()
        if not text:
            continue
        out.append(SituationStep(text=text[:_MAX_TEXT_LEN], target=it.target))
        if len(out) >= _MAX_STEPS:
            break
    return out


def normalize_narrative(narrative: SituationNarrative) -> SituationNarrative:
    """Подрезать длину/список шагов — страховка от многословия модели."""
    return SituationNarrative(
        conclusion=narrative.conclusion.strip()[:_MAX_CONCLUSION_LEN],
        steps=_trim_steps(narrative.steps),
    )


def parse_stored_narrative(
    raw: dict[str, Any] | None,
    *,
    db_schema_version: int | None = None,
) -> SituationNarrative | None:
    """Прочитать jsonb кэша. Чужая schema_version или битый payload → None (перегенерировать)."""
    if db_schema_version is not None and db_schema_version != SCHEMA_VERSION:
        return None
    if not raw:
        return None
    if raw.get("schema_version") not in (None, SCHEMA_VERSION):
        return None
    if "whats_good" in raw or "whats_bad" in raw:
        return None
    # B-07: лишние ключи старых версий (если версия в jsonb вдруг совпала) игнорируем.
    allowed = set(SituationNarrative.model_fields)
    data = {k: v for k, v in raw.items() if k in allowed}
    try:
        return SituationNarrative(**data)
    except Exception:
        return None


def narrative_to_storage(narrative: SituationNarrative) -> dict[str, Any]:
    """Сериализация в jsonb с меткой версии (только актуальные поля B-07)."""
    payload = narrative.model_dump(mode="json")
    payload["schema_version"] = SCHEMA_VERSION
    return payload


def _now() -> datetime:
    return datetime.now(UTC)


def _pct(rate: float | None) -> str:
    if rate is None:
        return "—"
    return f"{round(rate * 1000) / 10:g}%"


def _job_brief(job: Job) -> SituationJobBrief:
    return SituationJobBrief(
        title=(job.title or "—").strip(),
        company=(job.company or "—").strip(),
        score=int(job.overall_score or 0),
        recommendation=job.recommendation,
        status=job.status,
        source=job.source,
    )


def _offer_brief(offer: Offer) -> SituationOfferBrief:
    days_until_deadline: int | None = None
    if offer.deadline is not None:
        deadline = offer.deadline if offer.deadline.tzinfo else offer.deadline.replace(tzinfo=UTC)
        days_until_deadline = (deadline - _now()).days
    return SituationOfferBrief(
        company=(offer.company or "").strip(),
        position=(offer.position or "").strip(),
        base_salary=offer.base_salary,
        base_salary_currency=offer.base_salary_currency,
        base_salary_period=offer.base_salary_period,
        work_format=offer.work_format,
        office_days_per_week=offer.office_days_per_week,
        status=offer.status,
        deadline=offer.deadline,
        days_until_deadline=days_until_deadline,
    )


async def _load_top_companies(
    *, account_id: int, db: Executor, limit: int = 10
) -> list[SituationCompanyBrief]:
    rows = await db.fetch(
        "select company, max(overall_score)::int as best_score, count(*)::int as jobs_count "
        "from jobs where account_id = $1 and overall_score is not null "
        "and coalesce(trim(company), '') <> '' "
        "group by company order by best_score desc, jobs_count desc limit $2",
        account_id,
        limit,
    )
    return [
        SituationCompanyBrief(
            company=str(r["company"]),
            best_score=int(r["best_score"] or 0),
            jobs_count=int(r["jobs_count"] or 0),
        )
        for r in rows
    ]


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _stage_deltas(later: FunnelAnalytics, earlier: FunnelAnalytics) -> dict[str, int]:
    later_reached = {s.stage: s.reached for s in later.stages}
    earlier_reached = {s.stage: s.reached for s in earlier.stages}
    return {
        stage: max(0, later_reached.get(stage, 0) - earlier_reached.get(stage, 0))
        for stage in FUNNEL_ORDER
    }


async def gather_retro_facts(
    period_days: int = RETRO_PERIOD_DAYS, *, account_id: int, db: Executor
) -> RetroFacts:
    """Факты периода ретро воронки аккаунта (RD-18/UX5-20): период vs предыдущий период той же
    длины. Read-only, без LLM.
    """
    now = _now()
    cutoff_1 = now - timedelta(days=period_days)
    cutoff_2 = now - timedelta(days=2 * period_days)

    job_rows, stage_rows, skip_rows, outcome_rows, revision_rows = await asyncio.gather(
        db.fetch("select id, status, created_at from jobs where account_id = $1", account_id),
        db.fetch(
            "select job_id, stage, changed_at from application_stages where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select skip_reason, scored_at from skipped_vacancies where account_id = $1",
            account_id,
        ),
        db.fetch(
            "select stage, recruiter_feedback, created_at from stage_outcomes "
            "where account_id = $1 and outcome = 'rejected' and created_at > $2 "
            "order by created_at desc limit $3",
            account_id,
            cutoff_1,
            _MAX_QUOTES,
        ),
        db.fetch("select created_at from score_revisions where account_id = $1", account_id),
    )
    fjobs = [(r["id"], r["status"], _aware(r["created_at"])) for r in job_rows]
    fstages = [(r["job_id"], r["stage"], _aware(r["changed_at"])) for r in stage_rows]

    funnel_now_cum = compute_funnel_at(fjobs, fstages, None)
    funnel_cut1_cum = compute_funnel_at(fjobs, fstages, cutoff_1)
    funnel_cut2_cum = compute_funnel_at(fjobs, fstages, cutoff_2)

    now_deltas = _stage_deltas(funnel_now_cum, funnel_cut1_cum)
    prev_deltas = _stage_deltas(funnel_cut1_cum, funnel_cut2_cum)
    funnel = [
        PeriodStageDelta(stage=stage, now=now_deltas.get(stage, 0), prev=prev_deltas.get(stage, 0))
        for stage in FUNNEL_ORDER
    ]

    now_skip: Counter[str] = Counter()
    prev_skip: Counter[str] = Counter()
    for r in skip_rows:
        when = _aware(r["scored_at"])
        if when is None:
            continue
        reason = canonical_skip_reason(r["skip_reason"])
        if when > cutoff_1:
            now_skip[reason] += 1
        elif when > cutoff_2:
            prev_skip[reason] += 1
    skip_reasons = [
        PeriodReasonCount(reason=label, now=now_skip.get(label, 0), prev=prev_skip.get(label, 0))
        for label in SELF_SKIP_REASONS
        if now_skip.get(label, 0) or prev_skip.get(label, 0)
    ]

    quotes = [
        HrRejectionQuote(
            stage=r["stage"],
            feedback=(r["recruiter_feedback"] or "").strip(),
            created_at=_aware(r["created_at"]) or now,
        )
        for r in outcome_rows
        if (r["recruiter_feedback"] or "").strip()
    ]

    rev_now = 0
    rev_prev = 0
    for r in revision_rows:
        when = _aware(r["created_at"])
        if when is None:
            continue
        if when > cutoff_1:
            rev_now += 1
        elif when > cutoff_2:
            rev_prev += 1

    return RetroFacts(
        period_days=period_days,
        funnel=funnel,
        skip_reasons=skip_reasons,
        hr_rejection_quotes=quotes,
        score_revisions_now=rev_now,
        score_revisions_prev=rev_prev,
        total_jobs=len(job_rows),
    )


async def gather_situation_facts(
    *, account_id: int, db: Executor | None = None, settings: CoreSettings | None = None
) -> SituationFacts:
    """Собрать вход аккаунта: market grid + source funnel + top jobs/companies + факты периода
    (ретро)."""
    from core.domains.career.search_state import get_current_state
    from core.domains.career.track_state import get_current_tracks
    from core.domains.market.market_grid import get_market_grid

    db = db or get_pool()
    cfg = settings or get_settings()
    # Вложенный gather: результаты не схлопываются в Unknown у pyright (лимит overload'ов).
    facts_gather = asyncio.gather(
        get_market_grid(account_id=account_id, db=db),
        get_search_metrics(account_id=account_id, db=db),
        list_jobs(limit=10, account_id=account_id, db=db),
        _load_top_companies(account_id=account_id, db=db, limit=10),
        gather_retro_facts(RETRO_PERIOD_DAYS, account_id=account_id, db=db),
    )
    earliest_fetch = db.fetchval(
        "select min(scored_at) from jobs where account_id = $1 and scored_at is not null",
        account_id,
    )
    offers_fetch = load_active_offers(max_age_days=180, account_id=account_id, db=db)
    search_mode_fetch = get_current_state(account_id=account_id, db=db)
    tracks_fetch = get_current_tracks(account_id=account_id, db=db)
    mode_gather = asyncio.gather(search_mode_fetch, tracks_fetch)
    (
        (grid, search, jobs, companies, retro),
        earliest,
        offers,
        (search_mode, tracks_state),
    ) = await asyncio.gather(facts_gather, earliest_fetch, offers_fetch, mode_gather)
    days_active: int | None = None
    if isinstance(earliest, datetime):
        anchor = earliest if earliest.tzinfo else earliest.replace(tzinfo=UTC)
        days_active = max(0, (_now() - anchor).days)
    return SituationFacts(
        grid=grid,
        search=search,
        top_jobs=[_job_brief(j) for j in jobs if j.overall_score is not None],
        top_companies=companies,
        active_offers=[_offer_brief(o) for o in offers],
        retro=retro,
        days_active=days_active,
        horizon_days=cfg.search_horizon_days,
        search_mode_label=search_mode.label,
        search_track_label=", ".join(tracks_state.labels),
    )


def _source_funnel_block(facts: SituationFacts) -> str:
    report = facts.search.source_funnel
    if not report.available:
        return report.note or "Мало данных для сравнения каналов."
    lines: list[str] = []
    for sl in report.slices:
        lines.append(
            f"{sl.label} ({sl.source}): в системе {sl.total}, откликов {sl.applied}, "
            f"ответ HR {sl.responded} ({_pct(sl.response_rate)}), офферов {sl.offers} "
            f"(offer-rate {_pct(sl.offer_rate)})"
        )
    return "\n".join(lines)


def _offer_chance_block(facts: SituationFacts) -> str:
    oc = next((c for c in facts.grid.cells if c.key == "offer_chance"), None)
    if oc is None or oc.value is None:
        return "Шанс офферов: данных нет."
    delta = f", Δ24ч {oc.delta:+g} п.п." if oc.delta not in (None, 0) else ""
    return f"Шанс офферов (grid #7): {oc.value}%{delta}"


def _active_offers_block(facts: SituationFacts) -> str:
    """OF-15: офферы в руках как факт - формулировка без совета принять/отклонить
    (feedback_llm_advice_not_user_decision), решение остаётся за кандидатом."""
    offers = facts.active_offers
    if not offers:
        return ""
    lines: list[str] = []
    for o in offers:
        period = "мес" if o.base_salary_period == "month" else "год"
        amount = (
            f"{o.base_salary:,}".replace(",", " ") + f" {o.base_salary_currency}/{period}"
            if o.base_salary
            else "сумма не указана"
        )
        office_note = ""
        if o.work_format == "hybrid" and o.office_days_per_week is not None:
            office_note = f", {o.office_days_per_week} дн. в офисе"
        if o.deadline is None:
            deadline_note = "дедлайна нет"
        elif o.days_until_deadline is not None and o.days_until_deadline < 0:
            deadline_note = "дедлайн прошёл"
        elif o.days_until_deadline is not None:
            deadline_note = f"осталось {o.days_until_deadline} дн."
        else:
            deadline_note = f"до {o.deadline.strftime('%d.%m.%Y')}"
        lines.append(
            f"{o.company or 'компания не указана'} ({o.position or 'должность не указана'}): "
            f"{amount}, формат {o.work_format}{office_note}, статус {o.status}, {deadline_note}"
        )
    return "\n".join(lines)


def _top_jobs_block(jobs: list[SituationJobBrief]) -> str:
    if not jobs:
        return "Топ вакансий по скору: нет заскоренных."
    return "\n".join(
        f"{i + 1}. {j.score} · {j.company} · {j.title}"
        + (f" · {j.recommendation}" if j.recommendation else "")
        + (f" · {j.status}" if j.status else "")
        for i, j in enumerate(jobs)
    )


def _top_companies_block(companies: list[SituationCompanyBrief]) -> str:
    if not companies:
        return "Топ компаний: нет данных."
    return "\n".join(
        f"{i + 1}. {c.company} · лучший скор {c.best_score} · {c.jobs_count} вак."
        for i, c in enumerate(companies)
    )


def _fmt_period_delta(now: int, prev: int) -> str:
    if prev == 0 and now == 0:
        return f"{now} (было {prev})"
    trend = "рост" if now > prev else "спад" if now < prev else "без изменений"
    return f"{now} (было {prev}, {trend})"


def _period_funnel_block(retro: RetroFacts) -> str:
    lines = [f"{d.stage}: {_fmt_period_delta(d.now, d.prev)} за период" for d in retro.funnel]
    return "\n".join(lines) if lines else "(воронка пуста)"


def _period_skip_block(retro: RetroFacts) -> str:
    if not retro.skip_reasons:
        return "(за период ручных пропусков не было)"
    return "\n".join(f"{r.reason}: {_fmt_period_delta(r.now, r.prev)}" for r in retro.skip_reasons)


def _period_quotes_block(retro: RetroFacts) -> str:
    if not retro.hr_rejection_quotes:
        return "(фидбека рекрутёров по отказам за период нет)"
    return "\n".join(f'- [{q.stage}] "{q.feedback}"' for q in retro.hr_rejection_quotes)


def _period_revisions_block(retro: RetroFacts) -> str:
    return (
        f"Пересчётов скоринга по HR-фактам за период: {retro.score_revisions_now} "
        f"(было {retro.score_revisions_prev})"
    )


def _situation_goal_block(
    profile: SearchProfile,
    *,
    horizon_days: int,
    target_companies: list[str] | None = None,
) -> str:
    """Блок ЦЕЛЬ из SearchProfile. Пустой профиль - честный отказ додумывать цель."""
    formats: list[str] = []
    if profile.allows_remote:
        formats.append("удалённый")
    if profile.allows_hybrid:
        formats.append("гибрид")
    if profile.allows_office:
        formats.append("офис")

    companies = [c.strip() for c in (target_companies or []) if c and str(c).strip()]
    has_goal = bool(
        profile.title.strip()
        or profile.salary_min > 0
        or profile.market_segment.strip()
        or formats
        or companies
    )
    if not has_goal:
        return "Цель поиска в резюме не описана - не додумывай её, опирайся только на цифры ниже."

    lines: list[str] = []
    if profile.title.strip():
        lines.append(f"Должность: {profile.title.strip()}.")
    if formats:
        lines.append(f"Формат: {' / '.join(formats)}.")
    if profile.salary_min > 0:
        amount = f"{profile.salary_min:,}".replace(",", " ")
        currency = (profile.salary_currency or "RUB").strip().upper() or "RUB"
        sign = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency, currency)
        basis = "на руки" if profile.salary_basis == "net" else "до вычета"
        lines.append(f"Зарплата от {amount} {sign} {basis}/мес.")
    if profile.market_segment.strip():
        lines.append(f"Рынок: {profile.market_segment.strip()}.")
    # Рынок поиска (РФ / международный) — часть цели, а не фон: советы по каналам и темпу
    # для «Только РФ» и «Международный» разные.
    lines.append(f"Рынок поиска: {profile.market_scope_label}.")
    if companies:
        lines.append(f"Целевые компании: {', '.join(companies)}.")
    if profile.currently_employed is not None:
        lines.append(
            "Сейчас работает - выход требует отработки."
            if profile.currently_employed
            else "Сейчас без работы - может выйти быстро."
        )
    lines.append(f"Горизонт ~{horizon_days} дней.")
    return " ".join(lines)


def build_situation_user_prompt(
    facts: SituationFacts,
    *,
    profile: SearchProfile | None = None,
    target_companies: list[str] | None = None,
) -> str:
    """User-промпт: ЦЕЛЬ + grid JSON + шанс офферов + TOP + источники + ПЕРИОД."""
    timing = (
        f"Дней в активном поиске: {facts.days_active}."
        if facts.days_active is not None
        else "Дата старта поиска неизвестна."
    )
    if facts.search_mode_label:
        timing += f" Режим поиска: {facts.search_mode_label}."
    if facts.search_track_label:
        timing += f" Треки поиска: {facts.search_track_label}."
    note = ""
    if facts.grid.funnel_note:
        note = f"\nПримечание воронки: {facts.grid.funnel_note}\n"
    grid_json = format_market_grid_json_for_llm(facts.grid)

    goal_offer_note = ""
    offers_section = ""
    if facts.active_offers:
        n = len(facts.active_offers)
        goal_offer_note = (
            f"У кандидата уже есть {n} оффер(а) в руках (см. АКТИВНЫЕ ОФФЕРЫ) - сравнивай "
            "оставшийся поиск/финалы с этим фактом, не игнорируй его как уже решённое прошлое."
        )
        offers_section = f"\nАКТИВНЫЕ ОФФЕРЫ\n{_active_offers_block(facts)}\n"

    search_profile = profile if profile is not None else load_search_profile()
    if target_companies is None:
        try:
            data = read_default_resume_data()
            target_companies = list(data.search_criteria.target_companies or [])
        except Exception:  # noqa: BLE001 — цель не должна ронять сводку
            target_companies = []

    goal_line = _situation_goal_block(
        search_profile,
        horizon_days=facts.horizon_days,
        target_companies=target_companies,
    )

    return f"""ЦЕЛЬ
{goal_line}
{goal_offer_note}
{offers_section}
ТАЙМИНГ
{timing}
{note}
MARKET_GRID_JSON
Объективные агрегаты сетки «Рынок». У каждой метрики поле how — как считалась формула.
Используй ТОЛЬКО эти числа; не выдумывай метрик вне JSON.

```json
{grid_json}
```

OFFER_CHANCE
{_offer_chance_block(facts)}

TOP_JOBS (top-10 по overall_score)
{_top_jobs_block(facts.top_jobs)}

TOP_COMPANIES (top-10 по лучшему скору в корпусе)
{_top_companies_block(facts.top_companies)}

ИСТОЧНИКИ (hh / getmatch / habr / tg — куда бить объёмом в actions)
{_source_funnel_block(facts)}

ПЕРИОД (последние {facts.retro.period_days} дней против предыдущих {facts.retro.period_days} дней,
всего вакансий в системе: {facts.retro.total_jobs}) — не рынок вообще, а СВОЁ поведение за период

Воронка (сколько вакансий впервые дошло до ступени за период)
{_period_funnel_block(facts.retro)}

Причины ручного пропуска за период
{_period_skip_block(facts.retro)}

Цитаты фидбека рекрутёров по отказам за период (сырые, не перефразировать смысл)
{_period_quotes_block(facts.retro)}

{_period_revisions_block(facts.retro)}

Сделай сводку строго по входным блокам выше. Не выдумывай метрик и цитат, которых там нет.
Числа во входе - для анализа; в ответе дай текстовую интерпретацию, не копируй ряды цифр обратно."""


@lru_cache(maxsize=1)
def _situation_prompt_template() -> str:
    """Сырой текст файла-промпта сводки — кэш по пути, диск не перечитываем на каждый вызов."""
    from core.domains.market.llm import SITUATION

    path = Path(SITUATION)
    if not path.is_file():
        raise FileNotFoundError(f"Промпт сводки не найден: {path}")
    return path.read_text(encoding="utf-8").strip()


def _load_prompt(settings: CoreSettings, *, data: ResumeData | None = None) -> str:
    from core.domains.opportunities.prompt import CANDIDATE_IDENTITY_TOKEN, load_candidate_identity

    return _situation_prompt_template().replace(
        CANDIDATE_IDENTITY_TOKEN, load_candidate_identity(data=data)
    )


async def _situation_facts_and_prompt(
    *, account_id: int, db: Executor | None, cfg: CoreSettings
) -> tuple[str, str]:
    """Собрать факты аккаунта и построить system/user под LLM-вызов."""
    try:
        facts = await asyncio.wait_for(
            gather_situation_facts(account_id=account_id, db=db, settings=cfg),
            timeout=_FACTS_TIMEOUT_S,
        )
    except TimeoutError as exc:
        raise TimeoutError(
            f"Сбор данных для сводки завис дольше {_FACTS_TIMEOUT_S:.0f}с (БД?)"
        ) from exc
    if not facts.grid.available:
        raise ValueError("Недостаточно данных для сводки - сначала заскорь вакансии")

    from core.domains.profile.profile import load_candidate_profile_enriched
    from core.domains.profile.structured_store import read_resume_data_for_account

    resume_data = await read_resume_data_for_account(account_id, db=db)
    profile = await load_candidate_profile_enriched(account_id=account_id, data=resume_data, db=db)
    user_prompt = build_situation_user_prompt(
        facts,
        profile=profile,
        target_companies=list(resume_data.search_criteria.target_companies or []),
    )
    return _load_prompt(cfg, data=resume_data), user_prompt


async def _call_narrative(system: str, user: str) -> SituationNarrative:
    """Единственный structured-вызов сводки: схема из двух полей не упирается в лимит
    сложности Anthropic, поэтому split diagnosis/actions больше не нужен."""
    return await ports.llm().structured(
        "situation",
        system=system,
        user=user,
        schema=SituationNarrative,
        temperature=0.4,
    )


def _reraise_as_llm_error(exc: Exception) -> LlmError:
    if isinstance(exc, LlmError):
        return exc
    logger.exception("situation: structured output failed: %s", exc)
    return LlmError(f"Не удалось разобрать ответ модели: {exc}")


async def generate_situation_narrative(
    *, account_id: int, db: Executor | None = None, settings: CoreSettings | None = None
) -> SituationNarrative:
    """Сгенерировать сводку аккаунта reasoning-моделью по grid + facts."""
    cfg = settings or get_settings()
    if not cfg.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    system, user = await _situation_facts_and_prompt(account_id=account_id, db=db, cfg=cfg)

    try:
        narrative = await _call_narrative(system, user)
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001 — классифицируем в _reraise_as_llm_error
        raise _reraise_as_llm_error(exc) from exc

    result = normalize_narrative(narrative)
    event(
        logger,
        "LLM",
        "situation: вывод %d симв., шагов=%d",
        len(result.conclusion),
        len(result.steps),
        account_id=account_id,
        conclusion_chars=len(result.conclusion),
        steps=len(result.steps),
    )
    return result


async def generate_situation_narrative_events(
    *, account_id: int, db: Executor | None = None, settings: CoreSettings | None = None
) -> AsyncIterator[dict[str, Any]]:
    """Тот же расчёт, отдаёт статус, затем терминальный кадр (один вызов, не diagnosis/actions)."""
    cfg = settings or get_settings()
    if not cfg.openrouter_api_key:
        raise LlmError("OPENROUTER_API_KEY не задан")

    system, user = await _situation_facts_and_prompt(account_id=account_id, db=db, cfg=cfg)

    yield {"type": "status", "stage": "narrative", "label": "Считаю сводку"}

    try:
        narrative = await _call_narrative(system, user)
    except LlmError:
        raise
    except Exception as exc:  # noqa: BLE001 — классифицируем в _reraise_as_llm_error
        raise _reraise_as_llm_error(exc) from exc

    result = normalize_narrative(narrative)
    event(
        logger,
        "LLM",
        "situation: вывод %d симв., шагов=%d",
        len(result.conclusion),
        len(result.steps),
        account_id=account_id,
        conclusion_chars=len(result.conclusion),
        steps=len(result.steps),
    )
    yield {"type": "done", "narrative": result.model_dump(mode="json")}


__all__ = [
    "LEGACY_CACHE_NOTE",
    "RETRO_PERIOD_DAYS",
    "SCHEMA_VERSION",
    "HrRejectionQuote",
    "PeriodReasonCount",
    "PeriodStageDelta",
    "RetroFacts",
    "SituationCompanyBrief",
    "SituationFacts",
    "SituationJobBrief",
    "SituationNarrative",
    "SituationOfferBrief",
    "SituationStep",
    "SituationTarget",
    "SituationTargetSection",
    "_situation_goal_block",
    "build_situation_user_prompt",
    "gather_retro_facts",
    "gather_situation_facts",
    "generate_situation_narrative",
    "generate_situation_narrative_events",
    "narrative_to_storage",
    "normalize_narrative",
    "parse_stored_narrative",
]
