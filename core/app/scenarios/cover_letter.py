"""Сопроводительное письмо по вакансии.

Кросс-доменный сценарий: строка вакансии — `opportunities`, генерация — `pipeline`,
сборка `VacancyRecord` — `preparation.asker`. Раньше склейка жила в
`api/routers/pipeline/cover_letter.py`.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Literal

from pydantic import BaseModel

from core.kernel.errors import DomainError, InvalidInput, LlmError, NotFound, StorageUnavailable
from core.platform.observability import event
from core.platform.tasks import enqueue_soon, get_runtime

logger = logging.getLogger(__name__)

_NO_PG = "Postgres недоступен"
_MIN_TEXT = 50

# Троттл повторной постановки пре-генерации на один и тот же job. `preview_with_pregen` зовётся
# на КАЖДЫЙ GET /api/pipeline/auto-apply/preview, а фронт «Расширения» опрашивает превью раз в
# 5 секунд, пока страница открыта. Идемпотентность `enqueue` покрывает только PENDING/RUNNING —
# как только задача стала DONE или FAILED, следующий же опрос завёл бы НОВУЮ (для FAILED-письма,
# которое не сохранилось, — новый платный LLM-вызов каждые 5 секунд). Держим короткое окно
# «недавно ставили» в памяти процесса: письмо всё равно нужно не сейчас (priority 70), а до
# первого визита раннера расширения — 10 минут запаса достаточно.
_PREGEN_THROTTLE_SEC = 600.0
_recent_pregen: dict[tuple[int, int], float] = {}


def _pregen_recently_scheduled(job_id: int, *, account_id: int) -> bool:
    key = (account_id, job_id)
    now = time.monotonic()
    last = _recent_pregen.get(key)
    if last is not None and now - last < _PREGEN_THROTTLE_SEC:
        return True
    _recent_pregen[key] = now
    if len(_recent_pregen) > 4000:
        cutoff = now - _PREGEN_THROTTLE_SEC
        for stale in [k for k, ts in _recent_pregen.items() if ts < cutoff]:
            _recent_pregen.pop(stale, None)
    return False


# UX-правка 2026-08-20 (пункт 1): как только вакансия попадает в бакет «Автоотклик»
# (`preview_with_pregen` в `scenarios/auto_apply.py`), письмо без готового текста готовится в
# фоне тем же путём, что и ручная кнопка «Сгенерировать» — владельцу не нужно ждать первого
# визита раннера расширения или жать кнопку самому. Паттерн A-20 (см. `skip_reasons_async.py`):
# `platform.tasks`, не голый `asyncio.create_task` — дедуп по идемпотентному ключу, задача
# переживает рестарт процесса (PgTaskStore).
COVER_LETTER_PREGEN_KIND = "cover_letter_pregen"


def _pregen_idem_key(job_id: int, *, account_id: int) -> str:
    return f"{COVER_LETTER_PREGEN_KIND}:{account_id}:{job_id}"


async def cover_letter_pregen_running(job_id: int, *, account_id: int) -> bool:
    return await get_runtime().has_active(_pregen_idem_key(job_id, account_id=account_id))


def schedule_cover_letter_pregen(job_id: int, vacancy_text: str, *, account_id: int) -> None:
    """Поставить фоновую пре-генерацию письма, если текста вакансии достаточно, генерация ещё
    не идёт (дедуп `enqueue` по идемпотентному ключу) и её недавно не ставили
    (`_PREGEN_THROTTLE_SEC` — защита от 5-секундного опроса превью: без неё FAILED-письмо
    перезапускало бы платный LLM-вызов на каждый опрос)."""
    if len((vacancy_text or "").strip()) < _MIN_TEXT:
        return
    if _pregen_recently_scheduled(job_id, account_id=account_id):
        return
    enqueue_soon(
        COVER_LETTER_PREGEN_KIND,
        payload={"job_id": job_id, "account_id": account_id},
        priority=70,  # ниже skip_reasons (60) — письмо не нужно прямо сейчас, есть время до отклика
        idempotency_key=_pregen_idem_key(job_id, account_id=account_id),
        max_attempts=2,
        account_id=account_id,
    )
    event(
        logger,
        "ЗАДАЧА",
        "пре-генерация сопроводительного в очереди: job_id=%s",
        job_id,
        job_id=str(job_id),
    )


async def run_cover_letter_pregen_from_payload(payload: dict[str, Any]) -> None:
    """Обработчик очереди `cover_letter_pregen` (регистрация — `core.app.background`)."""
    job_id = int(payload.get("job_id") or 0)
    account_id = int(payload.get("account_id") or 0)
    if not job_id or not account_id:
        raise ValueError("cover_letter_pregen: нужен job_id и account_id")
    try:
        await generate_for_job(job_id, account_id=account_id)
    except DomainError as exc:
        # NotFound/InvalidInput — вакансия успела уйти из очереди/текст пуст между постановкой
        # в очередь и разбором; не повод ретраить и шуметь ERROR.
        event(
            logger,
            "ЗАДАЧА",
            "пре-генерация сопроводительного пропущена: job_id=%s: %s",
            job_id,
            exc,
            job_id=str(job_id),
        )
        return
    event(
        logger,
        "ЗАДАЧА",
        "сопроводительное готово (пре-генерация): job_id=%s",
        job_id,
        job_id=str(job_id),
    )


class CoverLetterResult(BaseModel):
    """Итог генерации: id строки jobs + текст письма + язык."""

    id: int
    vacancy_id: str
    cover_letter_text: str
    lang: str = "ru"


async def generate_for_job(
    job_id: int, *, account_id: int, lang: Literal["ru", "en"] | None = None
) -> CoverLetterResult:
    """Сгенерировать сопроводительное под вакансию (LLM) и записать в `jobs.cover_letter_text`.

    `lang` — явный выбор переключалки RU/EN (дровер/расширение, Э4.4); `None` — язык выводится
    из текста резюме (`generate_cover_letter`).
    """
    from core.domains.opportunities.jobs import get_job, update_apply_fields
    from core.domains.pipeline.cover_letter import generate_cover_letter
    from core.domains.preparation.asker import record_from_request_fallback

    try:
        job = await get_job(job_id, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — без PG письмо некуда писать
        logger.error("Сопроводительное: чтение вакансии из Postgres не удалось: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc
    if job is None or job.id is None:
        raise NotFound(f"вакансия не найдена: {job_id}")

    text = (job.vacancy_text or "").strip()
    if len(text) < _MIN_TEXT:
        raise InvalidInput("текст вакансии пуст или слишком короткий")

    record = record_from_request_fallback(
        job.vacancy_id or str(job.id),
        vacancy_text=text,
        title=job.title,
        company=job.company,
        salary_text=job.salary_text,
    )
    try:
        letter, effective_lang = await generate_cover_letter(
            record, account_id=account_id, lang=lang
        )
    except LlmError:
        raise

    try:
        # FR3-65: letter_required — только сигнал площадки, не побочный эффект текста.
        await update_apply_fields(
            job.id,
            cover_letter_text=letter,
            cover_letter_lang=effective_lang,
            account_id=account_id,
        )
    except Exception as exc:  # noqa: BLE001 — письмо без персиста бесполезно
        logger.error("Сопроводительное: запись в Postgres не удалась: %s", exc)
        raise StorageUnavailable(_NO_PG) from exc

    return CoverLetterResult(
        id=job.id, vacancy_id=job.vacancy_id or "", cover_letter_text=letter, lang=effective_lang
    )


__all__ = [
    "COVER_LETTER_PREGEN_KIND",
    "CoverLetterResult",
    "cover_letter_pregen_running",
    "generate_for_job",
    "run_cover_letter_pregen_from_payload",
    "schedule_cover_letter_pregen",
]
