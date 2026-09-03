"""Живой пересчёт очереди автооткликов по текущим `jobs` — без персиста (Фаза 1).

Ничего не кэширует и не пишет: решение детерминировано по текущим `jobs` + `auto_apply_config`,
пересчитывается на каждый запрос превью. `excluded` тут не появляется — вызывающая сторона
(превью для владельца) хочет видеть только те две группы, где вообще есть решение.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from core.domains.opportunities.competition import parse_published_at
from core.domains.opportunities.jobs import (
    Job,
    list_jobs,
    list_jobs_applied_today_via,
    resolve_job_source_group,
)
from core.domains.pipeline.auto_apply.config import (
    AutoApplyOrder,
    AutoApplyPlatform,
    get_auto_apply_config,
)
from core.domains.pipeline.auto_apply.daily_cap import auto_apply_source
from core.domains.pipeline.auto_apply.gate import classify_for_auto_apply
from core.domains.pipeline.auto_apply.overrides import get_overrides
from core.kernel.schemas.funnel import FunnelStatus

# Фаза 6.1: вес штрафа за конкуренцию в композитном ранге "smart" — score - k*log(1+responses).
# Грубая первая прикидка (как пороги compute_competition_insight), не калибрована по проду:
# log(1+20 откликов) ≈ 3.0, k=5 → ~15 баллов штрафа, сопоставимо с одной осью скоринга.
# total_responses почти всегда None на hh.ru (площадка не отдаёт счётчик, см. competition.py) —
# такие вакансии получают нулевой штраф, не проваливаются в конец очереди молча.
_SMART_ORDER_K = 5.0


def _smart_rank_key(job: Job) -> float:
    score = job.overall_score if job.overall_score is not None else 0
    responses = job.total_responses if job.total_responses is not None else 0
    return score - _SMART_ORDER_K * math.log1p(responses)


def _sort_candidates(jobs: list[Job], order: AutoApplyOrder) -> list[Job]:
    """Порядок кандидатов в очереди (6.1) — раньше `config.order` ни на что не влиял, раннер
    брал `jobs.auto` в порядке `list_jobs` (ярус воронки + свежесть скоринга), не по смыслу
    настройки. Сортировка здесь — то единственное место, где очередь реально формируется для
    расширения (`AutoApplyRunnerDeps.loadPlatformStates`)."""
    if order == "smart":
        return sorted(jobs, key=_smart_rank_key, reverse=True)
    if order == "published_desc":
        # published_at — свободный текст с площадки ("21 мая 2026"), не ISO. Без даты — в
        # хвост, не мешает сортировке остальных вместо непредсказуемого текстового сравнения.
        return sorted(
            jobs,
            key=lambda j: parse_published_at(j.published_at) or date.min,
            reverse=True,
        )
    return sorted(
        jobs, key=lambda j: j.overall_score if j.overall_score is not None else 0, reverse=True
    )


@dataclass
class AutoApplyQueuePreview:
    platform: AutoApplyPlatform
    enabled: bool
    auto: list[Job]
    manual_review: list[Job]
    # Пункт 1 редизайна «Расширения» (2026-08-19): вакансии, отправленные автооткликом СЕГОДНЯ —
    # чтобы владелец видел «кто уже ушёл» в конце очереди, не только «кто следующий». Живой запрос
    # к application_stages (list_jobs_applied_today_via), не часть auto/manual_review — эти жобы
    # уже не в статусе «Просмотрено», классификатор их бы просто исключил.
    applied: list[Job]
    # job_id → причина системного переноса в «Ручной разбор» после сбоя автоотклика (0153).
    failure_reasons: dict[int, str]


async def preview_queue(platform: AutoApplyPlatform, *, account_id: int) -> AutoApplyQueuePreview:
    """Разбить непросмотренные-до-отклика вакансии площадки на auto / manual_review.

    Пункт 1 редизайна «Расширения»: очередь должна быть видна ВСЕГДА, а не только пока площадка
    реально включена — иначе владелец не может посмотреть, что бы система взяла сама, не рискуя
    ничего запускать. Классификация здесь всегда идёт с `enabled=True` (виртуально «включено» для
    целей превью); реальная защита — в `config.enabled` (`result.enabled`, ниже) и, отдельно, в
    самом раннере расширения (`auto-apply-runner.ts::loadPlatformStates` пропускает площадку,
    если `platformConfig.enabled` не взведён по-настоящему) — превью на это не влияет.
    """
    config = (await get_auto_apply_config(account_id=account_id)).platform(platform)
    preview_config = config.model_copy(update={"enabled": True})
    jobs = await list_jobs(status=FunnelStatus.VIEWED.value, limit=500, account_id=account_id)
    candidates = [j for j in jobs if resolve_job_source_group(j.source, j.vacancy_id) == platform]
    overrides = await get_overrides(
        [j.id for j in candidates if j.id is not None], account_id=account_id
    )

    auto: list[Job] = []
    manual_review: list[Job] = []
    failure_reasons: dict[int, str] = {}
    for job in candidates:
        record = overrides.get(job.id) if job.id is not None else None
        decision = classify_for_auto_apply(
            job,
            config=preview_config,
            override=record.override if record is not None else None,
        )
        if decision == "auto":
            auto.append(job)
        elif decision == "manual_review":
            manual_review.append(job)
            if job.id is not None and record is not None and record.reason:
                failure_reasons[job.id] = record.reason
    applied = await list_jobs_applied_today_via(auto_apply_source(platform), account_id=account_id)
    return AutoApplyQueuePreview(
        platform=platform,
        enabled=config.enabled,
        auto=_sort_candidates(auto, config.order),
        manual_review=_sort_candidates(manual_review, config.order),
        applied=applied,
        failure_reasons=failure_reasons,
    )


__all__ = ["AutoApplyQueuePreview", "preview_queue"]
