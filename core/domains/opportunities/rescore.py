"""Перескор всей базы вакансий аккаунта по текущей рубрике — без LLM (Этап 5 §5.2).

`overall_score` — детерминированная функция сохранённого `score` jsonb (модельный вывод LLM,
неизменный) + `vacancy_text` + текущих весов/профиля резюме: `apply_calibration` пересобирает
breakdown, гейты, мягкие калибровки и recommendation заново, ничего не спрашивая у LLM. Перескор
всей базы стоит 0 LLM-вызовов — то же самое снимает вопрос «перескоривать ли задним числом»
для Этапов 1–4 этого плана (plans/scoring_precision_2026_08_17.md §5.2).

Триггер — `ResumeUpdated` (см. `events.py`): правка резюме меняет веса/role_kind, и уже
проскоренные вакансии должны догнать новую рубрику, иначе доска снова сравнивает вакансии,
посчитанные разными линейками (D7).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from core.domains.opportunities.auto_weights import derive_auto_scoring_weights
from core.domains.opportunities.events import publish_vacancy_scored
from core.domains.opportunities.jobs import (
    SOURCE_HH_APPLY_STUB,
    SOURCE_SKIP_STUB,
    Job,
    list_jobs_for_rescore,
    update_job_score,
)
from core.domains.opportunities.models import ScoreResult, VacancyWorkTerms
from core.domains.opportunities.rules import (
    APPLY_MIN,
    MAYBE_MIN,
    STRONG_APPLY_MIN,
    CompanyAdjustmentRule,
    apply_calibration,
    format_prefs_from_profile,
    load_list_company_adjustments,
    load_manual_company_adjustments,
)
from core.domains.opportunities.score_breakdown import resolve_weights, salary_prefs_from_profile
from core.domains.opportunities.scorer import _load_skill_overlap
from core.domains.opportunities.track_classify import classify_track
from core.domains.opportunities.weights_version import compute_weights_version
from core.domains.profile.profile import derive_candidate_profile
from core.domains.profile.structured_store import read_resume_data_for_account
from core.kernel.schemas.track import DEFAULT_TRACKS, SearchTrack
from core.platform.observability import event
from core.platform.tasks import enqueue_soon, get_runtime

if TYPE_CHECKING:
    from core.domains.profile.profile import CandidateProfile

logger = logging.getLogger(__name__)

RESCORE_WEIGHTS_KIND = "rescore_weights_version"

# Стаб-записи (D16, plans/scoring_precision_2026_08_17.md §8.3) без реального скоринга —
# формально проходят SQL-фильтр `list_jobs_for_rescore` по старым записям, если score когда-то
# был непустым (не должно случаться, но лишняя проверка дешевле разбора битой строки).
_STUB_SOURCES = frozenset({SOURCE_SKIP_STUB, SOURCE_HH_APPLY_STUB})


def _idem_key(account_id: int) -> str:
    return f"{RESCORE_WEIGHTS_KIND}:{account_id}"


async def rescore_task_running(account_id: int) -> bool:
    return await get_runtime().has_active(_idem_key(account_id))


def schedule_rescore_all(account_id: int) -> None:
    """Поставить полный перескор аккаунта в очередь. Идемпотентно по account_id — повторное
    сохранение резюме до завершения прошлого перескора не плодит вторую задачу (idempotency_key
    дедупит только pending/running, см. `platform.tasks.store`)."""
    if not account_id:
        return
    enqueue_soon(
        RESCORE_WEIGHTS_KIND,
        payload={"account_id": account_id},
        priority=120,  # ниже пользовательских догонок (salary=50, skip_reasons=60)
        idempotency_key=_idem_key(account_id),
        max_attempts=2,
        account_id=account_id,
    )
    event(
        logger,
        "ЗАДАЧА",
        "перескор рубрики в очереди: аккаунт %d",
        account_id,
        account_id=account_id,
    )


async def run_rescore_from_payload(payload: dict[str, Any]) -> None:
    account_id = int(payload.get("account_id") or 0)
    if not account_id:
        raise ValueError("rescore_weights_version: нужен account_id")
    await rescore_all_with_current_weights(account_id)


@dataclass(frozen=True)
class _RescoreContext:
    """Аккаунт-уровневые входы пересчёта — не зависят от конкретной вакансии."""

    account_id: int
    profile: CandidateProfile
    scoring_weights: dict[str, int]
    second_job_weights: dict[str, int]
    manual_rules: list[CompanyAdjustmentRule]
    list_rules: list[CompanyAdjustmentRule]
    tracks_enabled: list[SearchTrack]
    candidate_city: str


def _work_terms_of(job: Job, override: VacancyWorkTerms | None = None) -> VacancyWorkTerms | None:
    if override is not None:
        return override
    if not job.work_terms:
        return None
    try:
        return VacancyWorkTerms.model_validate(job.work_terms)
    except Exception:  # noqa: BLE001 — битый jsonb не валит перескор
        return None


def _resolve_job_track(
    job: Job,
    terms: VacancyWorkTerms | None,
    *,
    tracks_enabled: list[SearchTrack],
    profile: CandidateProfile,
    force_track: SearchTrack | None = None,
) -> SearchTrack:
    if force_track in ("primary", "second_job"):
        return force_track
    if job.track_override and job.track in ("primary", "second_job"):
        return job.track  # type: ignore[return-value]
    return classify_track(terms, profile=profile, tracks_enabled=tracks_enabled).track


async def _resolve_rescore_context(account_id: int) -> _RescoreContext:
    """Всё, что нужно для пересчёта, читается ОДИН раз на весь аккаунт (не на вакансию):
    резюме/профиль/веса/правила компаний не зависят от конкретной вакансии."""
    data = await read_resume_data_for_account(account_id)
    profile = derive_candidate_profile(data)
    scoring_weights = derive_auto_scoring_weights(
        data, role_kind=profile.role_kind, travel_is_dealbreaker=profile.travel_is_dealbreaker
    )
    second_job_weights = derive_auto_scoring_weights(
        data,
        role_kind=profile.role_kind,
        travel_is_dealbreaker=profile.travel_is_dealbreaker,
        track="second_job",
    )
    manual_rules = await load_manual_company_adjustments(account_id)
    list_rules = load_list_company_adjustments(data)
    tracks_enabled: list[SearchTrack] = list(DEFAULT_TRACKS)
    try:
        from core.domains.career.track_state import get_current_tracks

        tracks_enabled = list((await get_current_tracks(account_id=account_id)).tracks)
    except Exception as exc:  # noqa: BLE001 — нет журнала → только основная
        logger.debug("треки поиска недоступны при перескоре: %s", exc)
    return _RescoreContext(
        account_id=account_id,
        profile=profile,
        scoring_weights=scoring_weights,
        second_job_weights=second_job_weights,
        manual_rules=manual_rules,
        list_rules=list_rules,
        tracks_enabled=tracks_enabled,
        candidate_city=(data.personal.city or "").strip(),
    )


async def _recompute_one(
    job: Job,
    *,
    ctx: _RescoreContext,
    scoring_weights: dict[str, int] | None = None,
    force_track: SearchTrack | None = None,
    terms_override: VacancyWorkTerms | None = None,
) -> ScoreResult | None:
    """Пересчитанный `ScoreResult` одной вакансии или `None` — нечего/нельзя пересчитывать."""
    if job.source in _STUB_SOURCES and not job.score:
        return None
    try:
        score = ScoreResult.model_validate(job.score)
    except Exception as exc:  # noqa: BLE001 — битая/легаси запись не валит весь перескор
        logger.debug("перескор: невалидный score у job %s: %s", job.id, exc)
        return None

    terms = _work_terms_of(job, terms_override)
    track = _resolve_job_track(
        job,
        terms,
        tracks_enabled=ctx.tracks_enabled,
        profile=ctx.profile,
        force_track=force_track,
    )
    weights = scoring_weights
    if weights is None:
        weights = ctx.second_job_weights if track == "second_job" else ctx.scoring_weights

    rate_floor, rate_n_obs = None, 0
    if track == "second_job" and terms is not None:
        try:
            from core.domains.opportunities.work_terms import fetch_rate_floor

            rate_floor, rate_n_obs = await fetch_rate_floor(
                currency=terms.currency,
                rate_period=terms.rate_period,
                account_id=ctx.account_id,
            )
        except Exception as exc:  # noqa: BLE001 — нейтраль оси
            logger.debug("rate floor недоступен при перескоре: %s", exc)

    skill_overlap = await _load_skill_overlap(job.vacancy_id, ctx.profile)
    recalibrated = apply_calibration(
        score,
        job.vacancy_text or "",
        company=job.company,
        company_adjustments=ctx.manual_rules,
        list_rules=ctx.list_rules,
        scoring_weights=weights,
        format_prefs=format_prefs_from_profile(ctx.profile),
        role_kind=ctx.profile.role_kind,
        salary_prefs=salary_prefs_from_profile(ctx.profile),
        skill_overlap=skill_overlap,
        candidate_company_types=ctx.profile.company_types,
        vacancy_id=job.vacancy_id,
        track=track,
        terms=terms,
        intl=ctx.profile.international,
        market_scope=ctx.profile.market_scope,
        candidate_city=ctx.candidate_city,
        rate_floor=rate_floor,
        rate_n_obs=rate_n_obs,
    )
    if job.is_archived and recalibrated.recommendation != "skip":
        # Тот же инвариант, что в score_vacancy/salary_async: архивную вакансию из skip
        # не выпускаем.
        recalibrated = recalibrated.model_copy(update={"recommendation": "skip"})
    return recalibrated


async def rescore_all_with_current_weights(account_id: int) -> int:
    """Пересчитать overall_score/breakdown/гейты у всех jd_only вакансий аккаунта. Ноль LLM.

    Возвращает число реально изменившихся строк (не совпадающих с прежним overall_score/
    recommendation/breakdown — пропуск неизменных экономит запись в БД на большинстве вакансий,
    когда веса не менялись по существу).
    """
    ctx = await _resolve_rescore_context(account_id)
    jobs = await list_jobs_for_rescore(account_id=account_id)

    changed = 0
    for job in jobs:
        recalibrated = await _recompute_one(job, ctx=ctx)
        if recalibrated is None:
            continue
        stored_breakdown = (job.score or {}).get("score_breakdown") or {}
        if (
            recalibrated.overall_score == job.overall_score
            and recalibrated.recommendation == job.recommendation
            and recalibrated.score_breakdown == stored_breakdown
            and recalibrated.track == (job.track or "primary")
        ):
            continue

        terms_dump = job.work_terms
        if terms_dump is None:
            parsed = _work_terms_of(job)
            terms_dump = parsed.model_dump(mode="json") if parsed else None
        await update_job_score(
            job.vacancy_id or "",
            overall_score=recalibrated.overall_score,
            recommendation=recalibrated.recommendation,
            score_json=recalibrated.model_dump(mode="json"),
            weights_version=recalibrated.weights_version or None,
            basis="jd_only",
            work_terms=terms_dump,
            track=recalibrated.track,
            account_id=account_id,
        )
        publish_vacancy_scored(
            vacancy_id=job.vacancy_id or "",
            job_id=job.id,
            overall_score=recalibrated.overall_score,
            recommendation=recalibrated.recommendation,
            account_id=account_id,
        )
        changed += 1

    event(
        logger,
        "ЗАДАЧА",
        "перескор рубрики готов: аккаунт %d, %d/%d изменилось",
        account_id,
        changed,
        len(jobs),
        account_id=account_id,
        changed=changed,
        total=len(jobs),
    )
    return changed


async def current_weights_version(account_id: int) -> str:
    """Версия рубрики, которой скорилась бы вакансия ПРЯМО СЕЙЧАС (для сравнения с
    `job.score_weights_version` на карточке — Этап 5 §5.3). Основной трек — для обратной
    совместимости карточек без `track`."""
    primary, _second = await current_weights_versions(account_id)
    return primary


async def current_weights_versions(account_id: int) -> tuple[str, str]:
    """Версии обеих рубрик (основная, вторая работа) — карточка сравнивает со своей."""
    ctx = await _resolve_rescore_context(account_id)
    primary = compute_weights_version(
        resolve_weights(ctx.scoring_weights),
        role_kind=ctx.profile.role_kind,
        thresholds=(STRONG_APPLY_MIN, APPLY_MIN, MAYBE_MIN),
    )
    second = compute_weights_version(
        resolve_weights(ctx.second_job_weights, track="second_job"),
        role_kind=ctx.profile.role_kind,
        thresholds=(STRONG_APPLY_MIN, APPLY_MIN, MAYBE_MIN),
        track="second_job",
    )
    return primary, second


async def resolve_current_weights(account_id: int) -> dict[str, int]:
    """Веса рубрики ПРЯМО СЕЙЧАС для аккаунта — переиспользуется отчётом (Этап 7 §7.2,
    `axis_alignment.build_axis_alignment_report`), чтобы не резолвить резюме/профиль второй раз
    отдельной SQL-цепочкой."""
    ctx = await _resolve_rescore_context(account_id)
    return ctx.scoring_weights


class SimulatedRank(BaseModel):
    """Одна вакансия в топ-20 «что если бы веса были другими» (Этап 7 §7.3)."""

    vacancy_id: str
    title: str | None = None
    company: str | None = None
    before_score: int
    after_score: int
    before_rank: int | None = None
    after_rank: int | None = None


async def simulate_weight_override(
    account_id: int,
    overrides: Mapping[str, int],
    *,
    limit: int = 20,
) -> list[SimulatedRank]:
    """Гипотетическая рубрика (текущие веса + `overrides`) поверх уже сохранённого `score` jsonb.

    Переиспользует ровно тот же путь, что и реальный перескор (`_resolve_rescore_context` /
    `_recompute_one` / `apply_calibration`) — единственная разница: веса берутся с наложенным
    `overrides`, и результат НИКУДА не пишется (`update_job_score`/`publish_vacancy_scored` не
    вызываются). Нужно советующей подсказке (`axis_alignment.suggest_weight_adjustment`)
    показать «как изменится топ-20», не трогая ни одной строки `jobs`. Ноль LLM.

    Возвращает объединение топ-N по текущему и по гипотетическому скору — так видно и то, что
    вошло бы в топ, и то, что из него выпало бы, а не только перестановку внутри одного и того
    же множества.
    """
    ctx = await _resolve_rescore_context(account_id)
    override_ints = {k: int(v) for k, v in overrides.items()}
    weights = resolve_weights({**ctx.scoring_weights, **override_ints})
    jobs = await list_jobs_for_rescore(account_id=account_id)

    pairs: list[tuple[str, Job, ScoreResult]] = []
    for job in jobs:
        if job.overall_score is None or not job.vacancy_id:
            continue
        recalibrated = await _recompute_one(
            job,
            ctx=ctx,
            scoring_weights=weights,
            force_track="primary",
        )
        if recalibrated is None:
            continue
        pairs.append((job.vacancy_id, job, recalibrated))

    by_current = sorted(pairs, key=lambda p: p[1].overall_score or 0, reverse=True)
    by_simulated = sorted(pairs, key=lambda p: p[2].overall_score, reverse=True)
    current_rank = {vid: i + 1 for i, (vid, _, _) in enumerate(by_current)}
    simulated_rank = {vid: i + 1 for i, (vid, _, _) in enumerate(by_simulated)}

    top_ids = {vid for vid, _, _ in by_current[:limit]} | {
        vid for vid, _, _ in by_simulated[:limit]
    }
    by_vacancy = {vid: (job, recalibrated) for vid, job, recalibrated in pairs}

    rows = [
        SimulatedRank(
            vacancy_id=vid,
            title=by_vacancy[vid][0].title,
            company=by_vacancy[vid][0].company,
            before_score=by_vacancy[vid][0].overall_score or 0,
            after_score=by_vacancy[vid][1].overall_score,
            before_rank=current_rank.get(vid),
            after_rank=simulated_rank.get(vid),
        )
        for vid in top_ids
    ]
    rows.sort(key=lambda r: r.after_rank or 10**9)
    return rows


async def recompute_job_weights(vacancy_id: str, *, account_id: int) -> Job | None:
    """Пересчитать рубрику ОДНОЙ вакансии (кнопка «Пересчитать» на карточке). Ноль LLM.

    Уже вход — тот же `_recompute_one`, что и у полного перескора: не заводим второй путь ради
    единственной вакансии. `None` — вакансии нет.

    `hr_confirmed` пропускаем как есть (тот же компромисс, что у `list_jobs_for_rescore`):
    `hr_format_override` со слов рекрутера в `job.score` не хранится, и узкий пересчёт без него
    тихо отменил бы override — вернул бы stale JD-гейт формата поверх подтверждённой HR удалёнки.
    """
    from core.domains.opportunities.jobs import get_job_by_vacancy_id

    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    if job is None or job.score_basis == "hr_confirmed":
        return job
    ctx = await _resolve_rescore_context(account_id)
    recalibrated = await _recompute_one(job, ctx=ctx)
    if recalibrated is None:
        return job
    terms_dump = job.work_terms
    await update_job_score(
        job.vacancy_id or "",
        overall_score=recalibrated.overall_score,
        recommendation=recalibrated.recommendation,
        score_json=recalibrated.model_dump(mode="json"),
        weights_version=recalibrated.weights_version or None,
        basis="jd_only",
        work_terms=terms_dump,
        track=recalibrated.track,
        account_id=account_id,
    )
    publish_vacancy_scored(
        vacancy_id=job.vacancy_id or "",
        job_id=job.id,
        overall_score=recalibrated.overall_score,
        recommendation=recalibrated.recommendation,
        account_id=account_id,
    )
    return await get_job_by_vacancy_id(vacancy_id, account_id=account_id)


async def apply_extracted_work_terms(
    job: Job,
    terms: VacancyWorkTerms,
    *,
    account_id: int,
) -> Job | None:
    """Денормализовать извлечённые условия и пересчитать карточку без LLM.

    Не публикует `VacancyScored`: вызывается из подписчика этого события, повторная
    публикация зациклила бы экстракцию.
    """
    if not job.vacancy_id:
        return job
    ctx = await _resolve_rescore_context(account_id)
    recalibrated = await _recompute_one(job, ctx=ctx, terms_override=terms)
    if recalibrated is None:
        return job
    return await update_job_score(
        job.vacancy_id,
        overall_score=recalibrated.overall_score,
        recommendation=recalibrated.recommendation,
        score_json=recalibrated.model_dump(mode="json"),
        weights_version=recalibrated.weights_version or None,
        basis="jd_only",
        work_terms=terms.model_dump(mode="json"),
        track=recalibrated.track,
        account_id=account_id,
    )


__all__ = [
    "RESCORE_WEIGHTS_KIND",
    "SimulatedRank",
    "apply_extracted_work_terms",
    "current_weights_version",
    "current_weights_versions",
    "recompute_job_weights",
    "rescore_all_with_current_weights",
    "rescore_task_running",
    "resolve_current_weights",
    "run_rescore_from_payload",
    "schedule_rescore_all",
    "simulate_weight_override",
]
