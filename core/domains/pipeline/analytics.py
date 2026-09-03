"""Аналитика воронки откликов (подшаг 1).

Делает накопленную статусную статистику читаемой: конверсия по этапам
(Просмотр → Отклик → Скрининг → Техничка → Финал → Оффер), доля ответов после отклика,
медианное время между этапами. Источник — Postgres (`jobs.status` + история
`application_stages`), тот же канон стадий, что в `core/kernel/schemas/funnel.py`.

Это честный предшественник подшага 2 («правки резюме на конверсии»): пока воронка
пустая (нет приглашений/офферов, одна версия резюме), связывать формулировки резюме с
конверсией статистически нечего — поле `enough_data` это и показывает в UI.

Вычисление (`compute_funnel_analytics`) — чистая функция над списками, тестируется без БД;
переиспользуется `pulse.py`/`source_funnel.py` — здесь нет собственной HTTP-ручки.
"""

from __future__ import annotations

from datetime import date, datetime
from statistics import median

from pydantic import BaseModel, Field

from core.kernel.schemas.funnel import (
    FunnelStatus,
    funnel_stage_number,
    is_engaged_status,
    resolve_funnel_status,
)

# Путь кандидата (восходящие стадии). «Отказ»/«Архив» — терминальные, не в этой шкале.
FUNNEL_ORDER: tuple[str, ...] = (
    FunnelStatus.VIEWED,
    FunnelStatus.APPLIED,
    FunnelStatus.SCREENING,
    FunnelStatus.TECH,
    FunnelStatus.FINAL,
    FunnelStatus.OFFER,
)
_REJECTED: frozenset[str] = frozenset({FunnelStatus.REJECTED, FunnelStatus.ARCHIVE})

# Порог «данных достаточно для выводов по резюме» (подшаг 2). Ниже — UI честно говорит «копим».
_MIN_APPLIED = 10


class StageStat(BaseModel):
    """Одна ступень воронки: сколько вакансий дошли минимум до неё + конверсия с прошлой."""

    stage: str
    stage_number: int
    reached: int
    conversion_from_prev: float | None = None  # reached / reached(prev); None у первой ступени


class TransitionTime(BaseModel):
    """Медианное время перехода между соседними ступенями (по отметкам в системе)."""

    from_stage: str
    to_stage: str
    median_days: float | None = None
    sample_size: int = 0


class FunnelAnalytics(BaseModel):
    total_scored: int = 0  # все оценённые вакансии = достигли «Просмотр»
    applied: int = 0  # достигли «Отклик»
    responded: int = 0  # достигли «Скрининг» (HR ответил)
    interviewing: int = 0  # достигли «Техничка»
    offers: int = 0  # достигли «Оффер»
    rejected: int = 0  # терминальный «Отказ»/«Архив»
    response_rate: float | None = None  # responded / applied
    offer_rate: float | None = None  # offers / applied
    stages: list[StageStat] = Field(default_factory=list)
    transitions: list[TransitionTime] = Field(default_factory=list)
    enough_data: bool = False  # хватает ли воронки для выводов по резюме (подшаг 2)
    note: str | None = None  # пояснение, когда данных мало (RU, для UI)
    # Разбивка «Отклик» по факту просмотра HR — самое узкое место воронки: «не
    # просмотрено» (фейк-вакансия/низко в выдаче) и «просмотрено, молчат» (резюме не цепляет) —
    # два разных диагноза, jobs.status их не различает (просмотр != скрининг).
    applied_not_viewed: int = 0
    applied_viewed_pending: int = 0
    median_days_to_view: float | None = None


def _ratio(num: int, denom: int) -> float | None:
    return round(num / denom, 4) if denom else None


def _furthest_stage(statuses: list[str | None]) -> int:
    """Самая дальняя восходящая ступень из набора статусов (история + текущий).

    Любая запись в `jobs` = минимум «Просмотр» (её оценили), поэтому база 1. «Отказ»/«Архив»
    (stage_number 0) не двигают шкалу: отклонённая после скрининга вакансия всё равно
    числится дошедшей до «Скрининг» — это видно по её истории.
    """
    nums = [1]
    for s in statuses:
        n = funnel_stage_number(s)
        if isinstance(n, int) and n > 0:
            nums.append(n)
    return max(nums)


def compute_funnel_analytics(
    jobs: list[tuple[int, str | None]],
    stages: list[tuple[int, str, datetime]],
) -> FunnelAnalytics:
    """Чистый расчёт воронки.

    `jobs` — (job_id, текущий status); `stages` — (job_id, stage, changed_at) из истории.
    Не зависит от БД — синтетику можно прогонять в тестах.
    """
    if not jobs:
        return FunnelAnalytics()

    # История по вакансии: список статусов + первое время достижения каждой ступени.
    history: dict[int, list[str]] = {}
    first_at: dict[int, dict[int, datetime]] = {}
    for job_id, stage, changed_at in stages:
        history.setdefault(job_id, []).append(stage)
        n = funnel_stage_number(stage)
        if isinstance(n, int) and n > 0 and changed_at is not None:
            slots = first_at.setdefault(job_id, {})
            if n not in slots or changed_at < slots[n]:
                slots[n] = changed_at

    reached = dict.fromkeys(range(1, len(FUNNEL_ORDER) + 1), 0)
    rejected = 0
    for job_id, status in jobs:
        if resolve_funnel_status(status) in _REJECTED:
            rejected += 1
        furthest = _furthest_stage([status, *history.get(job_id, [])])
        for n in range(1, furthest + 1):
            if n in reached:
                reached[n] += 1

    stage_stats: list[StageStat] = []
    for i, name in enumerate(FUNNEL_ORDER):
        n = i + 1
        prev = reached.get(n - 1)
        stage_stats.append(
            StageStat(
                stage=name,
                stage_number=n,
                reached=reached[n],
                conversion_from_prev=_ratio(reached[n], prev) if prev is not None else None,
            )
        )

    # Медиана времени между соседними ступенями (по первому достижению каждой).
    spans: dict[tuple[int, int], list[float]] = {}
    for slots in first_at.values():
        for n in range(1, len(FUNNEL_ORDER)):
            if n in slots and n + 1 in slots and slots[n + 1] >= slots[n]:
                days = (slots[n + 1] - slots[n]).total_seconds() / 86400.0
                spans.setdefault((n, n + 1), []).append(days)
    transitions = [
        TransitionTime(
            from_stage=FUNNEL_ORDER[n - 1],
            to_stage=FUNNEL_ORDER[n],
            median_days=round(median(spans[(n, n + 1)]), 1) if spans.get((n, n + 1)) else None,
            sample_size=len(spans.get((n, n + 1), [])),
        )
        for n in range(1, len(FUNNEL_ORDER))
    ]

    applied, responded = reached[2], reached[3]
    interviewing, offers = reached[4], reached[len(FUNNEL_ORDER)]
    enough_data = applied >= _MIN_APPLIED and (responded >= 3 or offers >= 1)
    note: str | None = None
    if not enough_data:
        note = (
            f"Статистики для выводов по резюме пока мало: {applied} откл., "
            f"{responded} ответ., {offers} офф. Правки резюме на данных включим, "
            f"когда наберётся воронка."
        )

    return FunnelAnalytics(
        total_scored=reached[1],
        applied=applied,
        responded=responded,
        interviewing=interviewing,
        offers=offers,
        rejected=rejected,
        response_rate=_ratio(responded, applied),
        offer_rate=_ratio(offers, applied),
        stages=stage_stats,
        transitions=transitions,
        enough_data=enough_data,
        note=note,
    )


def compute_viewed_stats(
    jobs: list[tuple[str | None, str | None, datetime | None]],
) -> tuple[int, int, float | None]:
    """(не просмотрено, просмотрено-молчат, медиана дней до просмотра) — чистая функция.

    `jobs` — (status, applied_at, hr_viewed_at). Разбивка считается только среди вакансий,
    ЗАСТРЯВШИХ на «Отклик» (дошли до Скрининга — вопрос «просмотрено ли» больше не актуален).
    Медиана дней до просмотра считается по всем вакансиям с обеими датами, независимо от
    текущей стадии (это метрика скорости реакции HR, не текущего застоя).
    """
    not_viewed = 0
    viewed_pending = 0
    days: list[float] = []
    for status, applied_at, hr_viewed_at in jobs:
        if resolve_funnel_status(status) == FunnelStatus.APPLIED:
            if hr_viewed_at is None:
                not_viewed += 1
            else:
                viewed_pending += 1
        if hr_viewed_at is not None and applied_at:
            try:
                applied_date = date.fromisoformat(applied_at[:10])
            except ValueError:
                continue
            delta_days = (hr_viewed_at.date() - applied_date).days
            if delta_days >= 0:
                days.append(float(delta_days))
    median_days = round(median(days), 1) if days else None
    return not_viewed, viewed_pending, median_days


def compute_funnel_at(
    jobs: list[tuple[int, str | None, datetime | None]],
    stages: list[tuple[int, str, datetime | None]],
    cutoff: datetime | None,
) -> FunnelAnalytics:
    """Воронка на момент `cutoff` (None = сейчас) — для дельт день-ко-дню.

    Реконструкция как в `pulse._build_bundle`: вакансия учтена, только если создана к `cutoff`;
    текущий `status` берём лишь для «сейчас» (для прошлого шкалу двигает только история этапов,
    обрезанная по `changed_at`). Дельта метрики = «сейчас» минус «сутки назад» по тем же строкам.
    """
    in_window = lambda dt: cutoff is None or (dt is not None and dt <= cutoff)  # noqa: E731
    seen = [(jid, (st if cutoff is None else None)) for jid, st, ca in jobs if in_window(ca)]
    seen_ids = {jid for jid, _ in seen}
    cut_stages = [
        (jid, s, ca)
        for jid, s, ca in stages
        if jid in seen_ids and ca is not None and in_window(ca)
    ]
    return compute_funnel_analytics(seen, cut_stages)


def count_active_as_of(
    jobs: list[tuple[int, str | None]],
    stages: list[tuple[int, str, datetime | None]],
    cutoff: datetime | None,
) -> int:
    """Число вакансий в активном статусе (Отклик/Скрининг/Техничка/Финал/Оффер) на `cutoff`.

    `cutoff=None` — сейчас, по текущему `jobs.status`. Для прошлого статус вакансии не
    `jobs.status` (он знает только «сейчас») — последняя строка `application_stages` с
    `changed_at <= cutoff`, тот же приём реконструкции, что `compute_funnel_at`. Используется
    для дельты «Что изменилось» (Э9.5) — оба конца дельты через эту функцию, чтобы сравнение
    было на одной и той же линейке (не смешивать с `opportunities.jobs.count_active_jobs`,
    у которой есть отдельный кейс «HR-диалог без формального отклика», сюда не перенесённый).
    """
    if cutoff is None:
        return sum(1 for _jid, status in jobs if is_engaged_status(status or ""))
    latest: dict[int, tuple[datetime, str]] = {}
    for jid, stage, changed_at in stages:
        if changed_at is None or changed_at > cutoff:
            continue
        current = latest.get(jid)
        if current is None or changed_at > current[0]:
            latest[jid] = (changed_at, stage)
    return sum(1 for _changed_at, stage in latest.values() if is_engaged_status(stage))
