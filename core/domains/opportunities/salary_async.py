"""Фоновая LLM-оценка вилки зарплаты после скоринга (не блокирует POST /score).

Тир — фича `salary_estimate` → reasoning (реестр LlmFeature). Результат пишется
в `jobs.score` / `jobs.salary` через `update_job_score`; расширение и веб поллит
`GET /score/{vacancy_id}/salary`.

A-20: работа идёт через `platform.tasks` (идемпотентный ключ `salary_estimate:{vid}`),
а не через голый `asyncio.create_task`.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domains.opportunities.events import publish_vacancy_scored
from core.domains.opportunities.jobs import get_job_by_vacancy_id, update_job_score
from core.domains.opportunities.models import ScoreResult
from core.domains.opportunities.salary_estimator import estimate_salary
from core.domains.opportunities.scorer import _merge_salary_estimate, recompute_salary_points
from core.platform.observability import event
from core.platform.tasks import enqueue_soon, get_runtime

logger = logging.getLogger(__name__)

# Канон kind в очереди A-20 (регистрируется в core.app.background).
SALARY_ESTIMATE_KIND = "salary_estimate"


def _idem_key(vacancy_id: str, *, account_id: int) -> str:
    # account_id в ключе (plans/multitenancy_gaps_2026_08_06.md §3.10, риски): vacancy_id —
    # публичный hh-id, два разных аккаунта могут одновременно скорить одну и ту же вакансию —
    # без account_id в ключе их фоновые оценки схлопнулись бы в одну, и второй аккаунт не
    # получил бы свою вилку (или получил бы результат чужого расчёта).
    return f"{SALARY_ESTIMATE_KIND}:{account_id}:{vacancy_id}"


async def salary_estimate_task_running(vacancy_id: str, *, account_id: int) -> bool:
    vid = (vacancy_id or "").strip()
    if not vid:
        return False
    return await get_runtime().has_active(_idem_key(vid, account_id=account_id))


def schedule_salary_estimate(
    vacancy_id: str,
    vacancy_text: str,
    score: ScoreResult,
    *,
    account_id: int,
) -> None:
    """Поставить фоновую оценку в очередь, если ещё не активна для этого vacancy_id.

    `account_id` едет в payload очереди — воркер обрабатывает задачу вне request-контекста,
    поэтому личность не восстановить иначе, чем сериализовав её вместе с задачей.
    """
    vid = (vacancy_id or "").strip()
    if not vid or not score.salary.estimate_pending:
        return

    enqueue_soon(
        SALARY_ESTIMATE_KIND,
        payload={
            "vacancy_id": vid,
            "vacancy_text": vacancy_text,
            "score": score.model_dump(mode="json"),
            "account_id": account_id,
        },
        priority=50,
        idempotency_key=_idem_key(vid, account_id=account_id),
        max_attempts=2,
        account_id=account_id,
    )
    event(logger, "ЗАДАЧА", "фоновая оценка вилки в очереди: %s", vid, vacancy_id=vid)


async def run_salary_estimate_from_payload(payload: dict[str, Any]) -> None:
    """Обработчик очереди `salary_estimate`.

    Контекст `score` из payload — снимок на момент enqueue, нужен только чтобы дать LLM
    company_type/grade (см. `_run_salary_estimate` → `estimate_salary`); сама запись в БД
    всегда читает свежий `job.score`. Раньше `ScoreResult.model_validate(raw_score)` падал
    здесь, ДО входа в `_run_salary_estimate` — единственное место, которое умеет снимать
    `estimate_pending` при ошибке. После двух ретраев очередь тихо сдавалась, и вилка
    оставалась в статусе pending навсегда (баг «висит на "оценка…"»). Невалидный контекст
    больше не валит задачу — оценка идёт без него, а не совсем не идёт.
    """
    vid = str(payload.get("vacancy_id") or "").strip()
    text = str(payload.get("vacancy_text") or "")
    raw_score = payload.get("score")
    account_id = int(payload.get("account_id") or 0)
    if not vid or not account_id:
        raise ValueError("salary_estimate: нужен vacancy_id и account_id")
    score: ScoreResult | None = None
    if isinstance(raw_score, dict):
        try:
            score = ScoreResult.model_validate(raw_score)
        except Exception as exc:  # noqa: BLE001 — контекст не критичен, оценка пойдёт без него
            event(
                logger,
                "ОШИБКА",
                "фоновая вилка: невалидный контекст score в payload %s, оцениваем без него: %s",
                vid,
                exc,
                level=logging.WARNING,
                vacancy_id=vid,
            )
    await _run_salary_estimate(vid, text, score, account_id=account_id)


async def _clear_pending_flag(
    vacancy_id: str,
    score: ScoreResult,
    *,
    account_id: int,
    job_id: int | None = None,
) -> None:
    """Снять estimate_pending при фейле/пустом ответе — UI перестаёт поллить.

    Публикует `VacancyScored` (как и удачный путь ниже) — иначе живые клиенты (SSE-подключённые,
    без периодического поллинга `["jobs"]`) никогда не узнают, что фон закончился, и шапка чата
    висит на «оценка…» бесконечно (баг: карточка правится только в БД, витрина не инвалидируется).
    """
    salary = score.salary.model_copy(update={"estimate_pending": False, "source": "none"})
    updated = score.model_copy(update={"salary": salary})
    await update_job_score(
        vacancy_id,
        overall_score=updated.overall_score,
        recommendation=updated.recommendation,
        score_json=updated.model_dump(mode="json"),
        salary_json=salary.model_dump(mode="json"),
        work_city=updated.work_city or None,
        weights_version=updated.weights_version or None,
        basis="salary_estimate",
        account_id=account_id,
    )
    publish_vacancy_scored(
        vacancy_id=vacancy_id,
        job_id=job_id,
        overall_score=updated.overall_score,
        recommendation=updated.recommendation,
        account_id=account_id,
    )


async def _run_salary_estimate(
    vacancy_id: str, vacancy_text: str, score: ScoreResult | None, *, account_id: int
) -> None:
    try:
        from core.domains.profile.profile import derive_candidate_profile
        from core.domains.profile.structured_store import read_resume_data_for_account

        data = await read_resume_data_for_account(account_id)
        profile = derive_candidate_profile(data)
        estimate = await estimate_salary(vacancy_text, score, profile=profile)
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
        if job is None or not job.score:
            event(
                logger,
                "ЗАДАЧА",
                "фоновая вилка: job не найден %s",
                vacancy_id,
                level=logging.WARNING,
                vacancy_id=vacancy_id,
            )
            return

        base = ScoreResult.model_validate(job.score)
        from core.domains.opportunities.scorer import is_salary_locked

        if is_salary_locked(base.salary):
            event(
                logger,
                "ЗАДАЧА",
                "фоновая вилка пропуск: уже explicit %s",
                vacancy_id,
                vacancy_id=vacancy_id,
            )
            return

        if estimate is None:
            await _clear_pending_flag(vacancy_id, base, account_id=account_id, job_id=job.id)
            event(
                logger,
                "ЗАДАЧА",
                "фоновая вилка пусто: %s",
                vacancy_id,
                vacancy_id=vacancy_id,
            )
            return

        merged = _merge_salary_estimate(base, estimate)
        # Балл по зарплате считается по числам вилки (§2.1 плана), а на момент скоринга их не
        # было — без пересчёта ось так и осталась бы нейтральной у всех вакансий с фоновой
        # оценкой (81% базы прода). LLM здесь не зовём: рампа детерминирована.
        # Best-effort: срыв чтения резюме не должен стоить самой вилки — балл поправит любой
        # следующий пересчёт, а потерянная оценка стоила бы нового LLM-вызова.
        try:
            recomputed = await recompute_salary_points(merged, account_id=account_id)
            if job.is_archived and recomputed.recommendation != "skip":
                # Тот же инвариант, что в score_vacancy: архивную вакансию из skip не выпускаем.
                recomputed = recomputed.model_copy(update={"recommendation": "skip"})
            if recomputed.overall_score != merged.overall_score:
                event(
                    logger,
                    "ЗАДАЧА",
                    "фоновая вилка сдвинула балл: %s %d → %d",
                    vacancy_id,
                    merged.overall_score,
                    recomputed.overall_score,
                    vacancy_id=vacancy_id,
                    overall_score=recomputed.overall_score,
                    salary_source=recomputed.salary.source,
                    salary_confidence=recomputed.salary.confidence,
                )
            merged = recomputed
        except Exception as exc:  # noqa: BLE001 — вилку сохраняем даже без пересчёта балла
            event(
                logger,
                "ОШИБКА",
                "фоновая вилка: не пересчитали ось зарплаты для %s: %s",
                vacancy_id,
                exc,
                level=logging.WARNING,
                vacancy_id=vacancy_id,
            )
        await update_job_score(
            vacancy_id,
            overall_score=merged.overall_score,
            recommendation=merged.recommendation,
            score_json=merged.model_dump(mode="json"),
            salary_json=merged.salary.model_dump(mode="json"),
            work_city=merged.work_city or None,
            weights_version=merged.weights_version or None,
            basis="salary_estimate",
            account_id=account_id,
        )
        publish_vacancy_scored(
            vacancy_id=vacancy_id,
            job_id=job.id,
            overall_score=merged.overall_score,
            recommendation=merged.recommendation,
            account_id=account_id,
        )
        event(
            logger,
            "ЗАДАЧА",
            "фоновая вилка готова: %s (%s–%s)",
            vacancy_id,
            estimate.salary_min,
            estimate.salary_max,
            vacancy_id=vacancy_id,
        )
    except Exception as exc:  # noqa: BLE001 — фон не валит скоринг
        event(
            logger,
            "ОШИБКА",
            "фоновая вилка упала: %s: %s",
            vacancy_id,
            exc,
            level=logging.ERROR,
            exc_info=True,
            vacancy_id=vacancy_id,
        )
        try:
            job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
            if job and job.score:
                await _clear_pending_flag(
                    vacancy_id,
                    ScoreResult.model_validate(job.score),
                    account_id=account_id,
                    job_id=job.id,
                )
        except Exception as clear_exc:  # noqa: BLE001
            # DEBUG здесь означало, что вилка навсегда виснет в estimate_pending=True без
            # единого следа в бандле логов поддержки (sink — INFO+, см. CLAUDE.md) — владелец
            # видел бы только «оценка…» без объяснения. ERROR — вилка реально осталась битой.
            event(
                logger,
                "ОШИБКА",
                "фоновая вилка: не сняли estimate_pending для %s: %s",
                vacancy_id,
                clear_exc,
                level=logging.ERROR,
                exc_info=True,
                vacancy_id=vacancy_id,
            )
        # Не пробрасываем: UI уже снят с pending; повторный LLM-вызов через ретрай очереди
        # только жжёт бюджет. Инфра-сбой до try ловит воркер и ставит retry.


async def recompute_salary_estimate(vacancy_id: str, *, account_id: int) -> dict[str, Any] | None:
    """Кнопка «Обновить» у зарплаты (шапка чата вакансии / дровер) — узкий путь в обход полного
    `/score`: не трогает остальной скор, только заново запускает LLM-оценку вилки. None —
    вакансии с оценкой нет (роутер отдаёт 404).

    Зафиксированную вручную вилку (`source == "explicit"`) не трогаем — молча возвращаем текущее
    состояние, фронт объясняет по полю `source`, почему кнопка не сработала.
    """
    from core.domains.opportunities.jobs import get_job_by_vacancy_id, update_job_score
    from core.domains.opportunities.scorer import is_salary_locked

    job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
    if job is None or not job.score:
        return None

    score = ScoreResult.model_validate(job.score)
    if not is_salary_locked(score.salary):
        # schedule_salary_estimate() молча ничего не поставит в очередь, пока estimate_pending
        # не True (см. ниже по файлу) — выставляем и персистим сами: это не побочный эффект
        # полного /score, поэтому здесь его никто не выставит за нас.
        pending_salary = score.salary.model_copy(update={"estimate_pending": True})
        updated = score.model_copy(update={"salary": pending_salary})
        await update_job_score(
            vacancy_id,
            overall_score=updated.overall_score,
            recommendation=updated.recommendation,
            score_json=updated.model_dump(mode="json"),
            salary_json=pending_salary.model_dump(mode="json"),
            work_city=updated.work_city or None,
            basis="salary_estimate_manual",
            account_id=account_id,
        )
        schedule_salary_estimate(vacancy_id, job.vacancy_text or "", updated, account_id=account_id)
        job = await get_job_by_vacancy_id(vacancy_id, account_id=account_id)
        assert job is not None

    return await salary_payload_from_job(job, account_id=account_id)


_EMPTY_SALARY = frozenset({"", "?", "—", "-", "не указана", "не указан", "none"})


def _merged_has_salary(merged: dict[str, Any]) -> bool:
    """Вилка уже есть — UI не должен крутить спиннер, даже если estimate_pending залип."""
    if str(merged.get("source") or "") == "explicit":
        return True
    lo, hi = merged.get("estimated_min"), merged.get("estimated_max")
    if lo and hi:
        return True
    for key in ("estimated_range", "value_or_range"):
        val = str(merged.get(key) or "").strip().lower()
        if val and val not in _EMPTY_SALARY:
            return True
    return False


async def salary_payload_from_job(job: Any, *, account_id: int) -> dict[str, Any]:
    """Срез salary (+ pending) для poll-эндпоинта."""
    sal: dict[str, Any] = job.salary if isinstance(job.salary, dict) else {}
    score: dict[str, Any] = job.score if isinstance(job.score, dict) else {}
    raw_from_score = score.get("salary")
    from_score: dict[str, Any] = raw_from_score if isinstance(raw_from_score, dict) else {}
    merged = {**from_score, **sal}
    vid = job.vacancy_id or ""
    pending = bool(merged.get("estimate_pending")) and not _merged_has_salary(merged)
    running = await salary_estimate_task_running(vid, account_id=account_id)
    return {
        "vacancy_id": vid,
        "estimate_pending": pending,
        "estimated_range": merged.get("estimated_range") or "",
        "estimated_min": merged.get("estimated_min"),
        "estimated_max": merged.get("estimated_max"),
        "value_or_range": merged.get("value_or_range") or "",
        "meets_min": bool(merged.get("meets_min", False)),
        "note": merged.get("note") or "",
        "confidence": merged.get("confidence") or "low",
        "source": merged.get("source") or "none",
        # Не держим клиента в поллинге, если вилка уже на экране.
        "task_running": running if pending else False,
    }
