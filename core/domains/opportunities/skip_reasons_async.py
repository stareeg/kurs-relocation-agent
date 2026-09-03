"""Фоновая генерация LLM-причин пропуска после скоринга (не блокирует POST /score).

Тир — фича `skip_reasons_gen` → extract (реестр LlmFeature). Результат пишется
в таблицу `job_skip_reasons` (миграция 0100); расширение и веб тянут его через
`GET /vacancies/{id}/skip-reasons`.

A-20: работа идёт через `platform.tasks` (идемпотентный ключ `skip_reasons:{vid}`),
а не через голый `asyncio.create_task` — зеркально `salary_async.py`.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domains.opportunities.models import ScoreResult, SkipReasonsPack, SkipReasonSuggestion
from core.domains.opportunities.skip_reasons_gen import generate_skip_reasons
from core.platform.db.pool import Executor, get_pool, row_to_dict
from core.platform.observability import event
from core.platform.tasks import enqueue_soon, get_runtime

logger = logging.getLogger(__name__)

# Канон kind в очереди A-20 (регистрируется в core.app.background).
SKIP_REASONS_KIND = "skip_reasons"


def _idem_key(vacancy_id: str, *, account_id: int) -> str:
    # account_id в ключе: vacancy_id — публичный hh-id, два разных аккаунта
    # могут одновременно скорить одну вакансию — без account_id их генерации
    # схлопнулись бы в одну.
    return f"{SKIP_REASONS_KIND}:{account_id}:{vacancy_id}"


async def skip_reasons_task_running(vacancy_id: str, *, account_id: int) -> bool:
    vid = (vacancy_id or "").strip()
    if not vid:
        return False
    return await get_runtime().has_active(_idem_key(vid, account_id=account_id))


def schedule_skip_reasons(
    vacancy_id: str,
    vacancy_text: str,
    score: ScoreResult,
    *,
    account_id: int,
) -> None:
    """Поставить фоновую генерацию причин в очередь, если ещё не активна."""
    vid = (vacancy_id or "").strip()
    if not vid:
        return
    enqueue_soon(
        SKIP_REASONS_KIND,
        payload={
            "vacancy_id": vid,
            "vacancy_text": vacancy_text,
            "score": score.model_dump(mode="json"),
            "account_id": account_id,
        },
        priority=60,  # ниже salary_estimate (50), но выше тяжёлых задач
        idempotency_key=_idem_key(vid, account_id=account_id),
        max_attempts=2,
        account_id=account_id,
    )
    event(logger, "ЗАДАЧА", "генерация причин пропуска в очереди: %s", vid, vacancy_id=vid)


async def run_skip_reasons_from_payload(payload: dict[str, Any]) -> None:
    """Обработчик очереди `skip_reasons`."""
    vid = str(payload.get("vacancy_id") or "").strip()
    text = str(payload.get("vacancy_text") or "")
    raw_score = payload.get("score")
    account_id = int(payload.get("account_id") or 0)
    if not vid or not isinstance(raw_score, dict) or not account_id:
        raise ValueError("skip_reasons: нужен vacancy_id, score и account_id")
    score = ScoreResult.model_validate(raw_score)
    await _run_skip_reasons(vid, text, score, account_id=account_id)


async def _run_skip_reasons(
    vacancy_id: str, vacancy_text: str, score: ScoreResult, *, account_id: int
) -> None:
    try:
        pack = await generate_skip_reasons(vacancy_text, score)
        if pack is None:
            event(
                logger,
                "ЗАДАЧА",
                "причины пропуска пусто: %s",
                vacancy_id,
                vacancy_id=vacancy_id,
            )
            return
        await save_skip_reasons(vacancy_id, pack, account_id=account_id)
        event(
            logger,
            "ЗАДАЧА",
            "причины пропуска готовы: %s (%d чипов)",
            vacancy_id,
            len(pack.reasons),
            vacancy_id=vacancy_id,
        )
    except Exception as exc:  # noqa: BLE001 — фон не валит скоринг
        event(
            logger,
            "ОШИБКА",
            "генерация причин пропуска упала: %s: %s",
            vacancy_id,
            exc,
            level=logging.ERROR,
            exc_info=True,
            vacancy_id=vacancy_id,
        )


async def save_skip_reasons(
    vacancy_id: str, pack: SkipReasonsPack, *, account_id: int, db: Executor | None = None
) -> None:
    """Upsert пакета причин в `job_skip_reasons`."""
    if not vacancy_id:
        return
    db = db or get_pool()
    reasons_json = pack.model_dump(mode="json")
    await db.execute(
        "insert into job_skip_reasons (vacancy_id, account_id, reasons) "
        "values ($1, $2, $3) "
        "on conflict (account_id, vacancy_id) do update set "
        "reasons = excluded.reasons, generated_at = now()",
        vacancy_id,
        account_id,
        reasons_json,
    )


async def load_skip_reasons(
    vacancy_id: str, *, account_id: int, db: Executor | None = None
) -> SkipReasonsPack | None:
    """Прочитать пакет причин для вакансии. None — записей нет."""
    if not vacancy_id:
        return None
    db = db or get_pool()
    row = await db.fetchrow(
        "select reasons from job_skip_reasons where vacancy_id = $1 and account_id = $2",
        vacancy_id,
        account_id,
    )
    if row is None:
        return None
    data = row_to_dict(row)
    reasons_raw = data.get("reasons")
    if not isinstance(reasons_raw, dict):
        return None
    reasons_list = reasons_raw.get("reasons")
    if not isinstance(reasons_list, list):
        return None
    try:
        return SkipReasonsPack(
            reasons=[SkipReasonSuggestion.model_validate(r) for r in reasons_list]
        )
    except Exception as exc:  # noqa: BLE001 — битая запись — не валит UI
        logger.debug("job_skip_reasons: невалидный json для %s: %s", vacancy_id, exc)
        return None


async def skip_reasons_payload_from_job(vacancy_id: str, *, account_id: int) -> dict[str, Any]:
    """Срез для poll-эндпоинта: причины + task_running."""
    pack = await load_skip_reasons(vacancy_id, account_id=account_id)
    return {
        "vacancy_id": vacancy_id,
        "reasons": [r.model_dump(mode="json") for r in pack.reasons] if pack else [],
        "task_running": await skip_reasons_task_running(vacancy_id, account_id=account_id),
    }


__all__ = [
    "SKIP_REASONS_KIND",
    "load_skip_reasons",
    "run_skip_reasons_from_payload",
    "schedule_skip_reasons",
    "skip_reasons_payload_from_job",
    "skip_reasons_task_running",
]
