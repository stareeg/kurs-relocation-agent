"""Сбор статистики по вакансиям и собеседованиям (из bot_app.services.job_stats).

Вакансии — opportunities.jobs; пропуски — opportunities.skipped; этапы —
preparation.interview_stages; молчащий HR — opportunities.enrichment.
`JobMarketStats` — агрегаты для бота (/status) и прочего market-отчёта.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from core.domains.opportunities.enrichment import load_stale_hr_contacts
from core.domains.opportunities.jobs import list_jobs
from core.domains.opportunities.skipped import count_skipped, load_skipped_list
from core.domains.preparation.interview_stages import load_upcoming_stages

logger = logging.getLogger(__name__)

# Потолок выборки вакансий для агрегации (на инсталляцию — сотни записей; запас на вырост).
_MAX_JOBS = 5000

REC_LABELS = {
    "strong_apply": "подать обязательно",
    "apply": "подать",
    "maybe": "сомнение",
    "skip": "пропустить",
}


@dataclass
class JobMarketStats:
    total_vacancies: int = 0
    avg_score: float = 0.0
    scored_today: int = 0
    scored_last_7_days: int = 0
    recommendations: dict[str, int] = field(default_factory=dict)
    high_score: int = 0  # >= 70
    mid_score: int = 0  # 45-69
    low_score: int = 0  # < 45
    top_hit: str = ""
    top_hit_score: int = 0
    worst_hit: str = ""
    worst_hit_score: int = 100
    company_types: dict[str, int] = field(default_factory=dict)
    top_niches: list[str] = field(default_factory=list)
    upcoming_interviews: int = 0
    next_interview: str = ""
    stale_hr_count: int = 0
    stale_hr_hint: str = ""
    funnel_statuses: dict[str, int] = field(default_factory=dict)
    skipped_total: int = 0
    skipped_last_7_days: int = 0

    def to_prompt_blob(self) -> str:
        """Компактный текст для LLM."""
        rec_parts = [
            f"{REC_LABELS.get(k, k)}: {v}"
            for k, v in sorted(
                self.recommendations.items(),
                key=lambda x: x[1],
                reverse=True,
            )
        ]
        lines = [
            f"Всего оценено вакансий: {self.total_vacancies}",
            f"Средний скор: {self.avg_score:.0f}/100",
            f"Оценено сегодня: {self.scored_today}",
            f"За последние 7 дней: {self.scored_last_7_days}",
            f"Скоры: зелёных (≥70) {self.high_score}, жёлтых (45-69) {self.mid_score}, "
            f"красных (<45) {self.low_score}",
            f"Рекомендации: {', '.join(rec_parts) if rec_parts else 'нет данных'}",
        ]
        if self.top_hit:
            lines.append(f"Лучшая: {self.top_hit} ({self.top_hit_score})")
        if self.worst_hit and self.total_vacancies > 1:
            lines.append(f"Худшая: {self.worst_hit} ({self.worst_hit_score})")
        if self.company_types:
            ct = ", ".join(f"{k}: {v}" for k, v in self.company_types.items())
            lines.append(f"Типы компаний: {ct}")
        if self.top_niches:
            lines.append(f"Частые ниши в хитах (≥70): {', '.join(self.top_niches[:4])}")
        if self.funnel_statuses:
            fs = ", ".join(f"{k}: {v}" for k, v in self.funnel_statuses.items())
            lines.append(f"Статусы воронки: {fs}")
        lines.append(f"Предстоящих собесов: {self.upcoming_interviews}")
        if self.next_interview:
            lines.append(f"Ближайший: {self.next_interview}")
        if self.stale_hr_count:
            lines.append(f"Без ответа HR >5 дней: {self.stale_hr_count} ({self.stale_hr_hint})")
        if self.skipped_total:
            lines.append(
                f"Пропущено (база решений): {self.skipped_total}"
                + (f", за 7 дней: {self.skipped_last_7_days}" if self.skipped_last_7_days else "")
            )
        return "\n".join(lines)


async def _fill_interview_stats(stats: JobMarketStats, *, account_id: int) -> None:
    try:
        upcoming = await load_upcoming_stages(days=30, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → раздел пуст
        logger.debug("job_stats: upcoming stages недоступны: %s", exc)
        return
    stats.upcoming_interviews = len(upcoming)
    if not upcoming:
        return
    first = upcoming[0]
    if first.scheduled_at:
        dt = first.scheduled_at.astimezone().strftime("%d.%m %H:%M")
        stats.next_interview = f"{first.vacancy_id} ({dt})"


async def _fill_stale_hr(stats: JobMarketStats, *, account_id: int) -> None:
    try:
        stale = await load_stale_hr_contacts(days=5, account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("job_stats: stale HR недоступны: %s", exc)
        return
    stats.stale_hr_count = len(stale)
    if not stale:
        return
    ids = [s.vacancy_id for s in stale[:3]]
    stats.stale_hr_hint = ", ".join(ids)
    if len(stale) > 3:
        stats.stale_hr_hint += f" +{len(stale) - 3}"


async def _fill_skipped(stats: JobMarketStats, week_ago: datetime, *, account_id: int) -> None:
    try:
        stats.skipped_total = await count_skipped(account_id=account_id)
        if stats.skipped_total:
            recent = await load_skipped_list(limit=200, account_id=account_id)
            stats.skipped_last_7_days = sum(
                1 for s in recent if s.scored_at and s.scored_at >= week_ago
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("job_stats: skipped недоступны: %s", exc)


async def collect_job_stats(*, account_id: int) -> JobMarketStats:
    stats = JobMarketStats()
    now = datetime.now(tz=UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)

    try:
        jobs = await list_jobs(limit=_MAX_JOBS, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — нет PG → только собесы/HR/skip (тоже мягко)
        logger.debug("job_stats: список вакансий недоступен: %s", exc)
        jobs = []

    stats.total_vacancies = len(jobs)

    scores: list[int] = []
    rec_counter: Counter[str] = Counter()
    type_counter: Counter[str] = Counter()
    niche_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()

    for job in jobs:
        data = job.score or {}
        score = int(
            job.overall_score
            if job.overall_score is not None
            else data.get("overall_score", 0) or 0
        )
        scores.append(score)

        if score >= 70:
            stats.high_score += 1
            for niche in (data.get("role_content_match") or {}).get("matched_niche") or []:
                niche_counter[niche] += 1
        elif score >= 45:
            stats.mid_score += 1
        else:
            stats.low_score += 1

        rec_counter[job.recommendation or data.get("recommendation") or "unknown"] += 1
        type_counter[data.get("company_type") or "unknown"] += 1

        if job.status:
            status_counter[job.status] += 1
        if job.scored_at and job.scored_at >= today_start:
            stats.scored_today += 1
        if job.scored_at and job.scored_at >= week_ago:
            stats.scored_last_7_days += 1

        label = f"{job.company or '?'} — {job.title or 'вакансия'}"
        if score > stats.top_hit_score:
            stats.top_hit_score = score
            stats.top_hit = label
        if score < stats.worst_hit_score:
            stats.worst_hit_score = score
            stats.worst_hit = label

    if scores:
        stats.avg_score = sum(scores) / len(scores)

    stats.recommendations = dict(rec_counter)
    stats.company_types = dict(type_counter)
    stats.top_niches = [n for n, _ in niche_counter.most_common(5)]
    stats.funnel_statuses = dict(status_counter)

    await asyncio.gather(
        _fill_skipped(stats, week_ago, account_id=account_id),
        _fill_interview_stats(stats, account_id=account_id),
        _fill_stale_hr(stats, account_id=account_id),
    )
    return stats
