"""Синхронный скоринг вакансии — путь расширения.

Контракт совместим по смыслу с расширением: вход {text, url, vacancy_id}, выход
VacancyRecord-подобный. Сам сценарий (скоринг + под-скор удалёнки + персист + фоновая вилка) —
`core.domains.opportunities.service.score_and_store`; роутер валидирует вход, зовёт сценарий и
раскладывает ошибку.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from api.errors import to_http
from api.routers.opportunities.mappers import score_response
from api.schemas import (
    SalaryEstimatePoll,
    ScoreRequest,
    ScoreResponse,
    SimulateWeightsRequest,
    SkipReasonsPoll,
    WeightsRecomputeOut,
    WeightsVersionOut,
)
from api.security import AccountContext, require_account_context
from core.domains.opportunities.axis_alignment import (
    AxisAlignmentReport,
    build_axis_alignment_report,
)
from core.domains.opportunities.jobs import get_job_by_vacancy_id
from core.domains.opportunities.models import ScoreResult, VacancyInput
from core.domains.opportunities.parser_health import (
    HH_VACANCY_PARSE_METHODS,
    note_hh_vacancy_parse,
)
from core.domains.opportunities.rescore import (
    SimulatedRank,
    current_weights_versions,
    recompute_job_weights,
    simulate_weight_override,
)
from core.domains.opportunities.salary_async import (
    recompute_salary_estimate,
    salary_payload_from_job,
)
from core.domains.opportunities.service import score_and_store
from core.domains.opportunities.skip_reasons_async import skip_reasons_payload_from_job
from core.kernel.errors import DomainError
from core.platform.observability import event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["score"])


def _log_parse_method(body: ScoreRequest) -> None:
    """Observability источника парсинга вакансии.

    getmatch: rsc → INFO; jsonld/dom → WARNING (запасной слой).
    hh: каждый разбор — INFO; доля structural > 10%/час → отдельный WARNING
    (`hh_selectors_dead`), без крона.
    """
    method = (body.parse_method or "").strip()
    if not method:
        return
    source = body.source or "?"
    is_hh = method in HH_VACANCY_PARSE_METHODS
    if is_hh:
        event(
            logger,
            "РАСШИРЕНИЕ",
            "метод парсинга: %s (%s)",
            method,
            source,
            level=logging.INFO,
            event="hh_parse_method",
            parse_method=method,
            vacancy_id=body.vacancy_id or "",
            source=source,
        )
        alert = note_hh_vacancy_parse(method)
        if alert is None:
            return
        event(
            logger,
            "РАСШИРЕНИЕ",
            "селекторы hh мертвы, серверный конфиг не спас",
            level=logging.WARNING,
            event="hh_selectors_dead",
            structural=alert.structural,
            total=alert.total,
            share=round(alert.share, 3),
        )
        return
    event(
        logger,
        "РАСШИРЕНИЕ",
        "метод парсинга: %s (%s)",
        method,
        source,
        level=_parse_method_level(method),
        parse_method=method,
        vacancy_id=body.vacancy_id or "",
        source=source,
    )


def _parse_method_level(method: str) -> int:
    return logging.INFO if method == "rsc" else logging.WARNING


@router.post("/score", response_model=ScoreResponse)
async def score_endpoint(
    body: ScoreRequest, account: AccountContext = Depends(require_account_context)
) -> ScoreResponse:
    """Оценить вакансию и best-effort сохранить (нет PG → `persisted=false`)."""
    _log_parse_method(body)
    vac = VacancyInput(**body.model_dump())
    try:
        outcome = await score_and_store(vac, account_id=account.account_id)
    except DomainError as exc:
        raise to_http(exc) from exc
    return score_response(vac, outcome)


@router.get("/score/{vacancy_id}/salary", response_model=SalaryEstimatePoll)
async def salary_estimate_poll(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> SalaryEstimatePoll:
    """Полл фоновой оценки вилки: расширение/веб подтягивают, когда estimate_pending снят."""
    job = await get_job_by_vacancy_id(vacancy_id, account_id=account.account_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    payload = await salary_payload_from_job(job, account_id=account.account_id)
    return SalaryEstimatePoll(**payload)


@router.post("/score/{vacancy_id}/salary/recompute", response_model=SalaryEstimatePoll)
async def salary_estimate_recompute(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> SalaryEstimatePoll:
    """Кнопка «Обновить» у зарплаты (шапка чата / дровер вакансии) — узкий путь в обход
    полного `/score`, см. `salary_async.recompute_salary_estimate`."""
    payload = await recompute_salary_estimate(vacancy_id, account_id=account.account_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    return SalaryEstimatePoll(**payload)


@router.get("/score/weights-version", response_model=WeightsVersionOut)
async def weights_version_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> WeightsVersionOut:
    """Версия рубрики скоринга ПРЯМО СЕЙЧАС (Этап 5 §5.1/§5.3) — карточка сравнивает её со
    своим `score_weights_version` и показывает «пересчитать», если рубрика уже другая."""
    primary, second = await current_weights_versions(account.account_id)
    return WeightsVersionOut(weights_version=primary, second_job_weights_version=second)


@router.post("/score/{vacancy_id}/recompute-weights", response_model=WeightsRecomputeOut)
async def recompute_weights_endpoint(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> WeightsRecomputeOut:
    """Кнопка «Пересчитать» на карточке — узкий пересчёт по текущей рубрике в обход полного
    `/score` (Этап 5 §5.3): без LLM, см. `rescore.recompute_job_weights`."""
    job = await recompute_job_weights(vacancy_id, account_id=account.account_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Вакансия не найдена")
    try:
        score = ScoreResult.model_validate(job.score) if job.score else None
    except Exception:  # noqa: BLE001 — stub-запись без валидного score, отдаём поля без него
        score = None
    return WeightsRecomputeOut(
        vacancy_id=job.vacancy_id,
        overall_score=job.overall_score,
        recommendation=job.recommendation,
        score=score,
        weights_version=job.score_weights_version or "",
    )


@router.get("/score/axis-alignment", response_model=AxisAlignmentReport)
async def axis_alignment_endpoint(
    account: AccountContext = Depends(require_account_context),
) -> AxisAlignmentReport:
    """Насколько оси скора совпадают с решениями владельца (Этап 7 §7.2) — read-only,
    ничего не пишет и не двигает веса рубрики автоматически."""
    try:
        return await build_axis_alignment_report(account.account_id)
    except Exception as exc:  # noqa: BLE001 — отчёт best-effort, не должен ронять экран «Рынок»
        logger.error("axis-alignment: не удалось построить отчёт: %s", exc)
        raise HTTPException(status_code=503, detail="Postgres недоступен") from exc


@router.post("/score/axis-alignment/simulate", response_model=list[SimulatedRank])
async def axis_alignment_simulate_endpoint(
    body: SimulateWeightsRequest,
    account: AccountContext = Depends(require_account_context),
) -> list[SimulatedRank]:
    """«Показать, как изменится топ-20» под советующую подсказку (Этап 7 §7.3): гипотетическая
    рубрика поверх уже сохранённого `score` jsonb, без LLM. Ничего не сохраняет — см.
    `rescore.simulate_weight_override`."""
    try:
        return await simulate_weight_override(account.account_id, body.overrides)
    except Exception as exc:  # noqa: BLE001
        logger.error("axis-alignment/simulate: не удалось посчитать превью: %s", exc)
        raise HTTPException(status_code=503, detail="Postgres недоступен") from exc


@router.get("/vacancies/{vacancy_id}/skip-reasons", response_model=SkipReasonsPoll)
async def skip_reasons_poll(
    vacancy_id: str, account: AccountContext = Depends(require_account_context)
) -> SkipReasonsPoll:
    """LLM-причины пропуска под вакансию: расширение/веб подтягивают чипы.

    Пустой `reasons` — LLM ещё не сгенерировал (или недоступен); UI падает на
    статичные канонические чипы из `SELF_SKIP_REASONS`. `task_running` — поллим.
    """
    payload = await skip_reasons_payload_from_job(vacancy_id, account_id=account.account_id)
    return SkipReasonsPoll(**payload)
