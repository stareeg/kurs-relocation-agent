"""Обработка очереди калибровки: батчи → LLM → Postgres (из bot_app.services).

Извлечение/префильтр/отчёт — `salary_calibration`; очередь/сэмплы — `salary_calib`.
Текст статуса принимает опциональные подсказки авто-разбора (их даёт канал-бот).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from core.domains.market.salary_calib import (
    count_queue,
    count_samples,
    enqueue_message,
    fetch_pending_batch,
    fetch_relevant_samples,
    insert_sample,
    mark_queue_status,
    requeue_processing,
)
from core.domains.market.salary_calibration import (
    build_calibration_report,
    extract_salary_batch,
    looks_like_salary_post,
)
from core.kernel.errors import LlmError
from core.platform.observability import event

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
BATCH_PAUSE_SEC = 1.5

ProgressFn = Callable[[int, int, int], Awaitable[None]]


async def process_pending_queue(
    *,
    max_batches: int | None = None,
    on_progress: ProgressFn | None = None,
) -> tuple[int, int, int]:
    """Обработать pending очередь. Returns (processed_posts, relevant_samples, errors).

    Очередь кросс-аккаунтная (в одном батче могут смешаться посты разных аккаунтов —
    у каждой строки свой `CalibQueueItem.account_id`), поэтому `account_id` ниже — не фильтр
    выборки, а атрибуция самого прогона джобы (кто её держит), тот же приём, что уже применён
    для системных фонов в `snapshot_refresh.py`.
    """
    from core.platform.repo.accounts import resolve_default_account_id

    account_id = await resolve_default_account_id()

    recovered = await requeue_processing()
    if recovered:
        event(
            logger,
            "ЗАДАЧА",
            "Salary calib: возвращено в pending из processing: %d",
            recovered,
            account_id=account_id,
        )

    processed = 0
    relevant = 0
    errors = 0
    batches_done = 0

    while True:
        if max_batches is not None and batches_done >= max_batches:
            break
        batch = await fetch_pending_batch(limit=BATCH_SIZE)
        if not batch:
            break

        ids = [int(item.id) for item in batch if item.id is not None]
        await mark_queue_status(ids, "processing")

        try:
            extracted = await extract_salary_batch(batch)
            for sample in extracted:
                await insert_sample(sample)
                if sample.is_relevant:
                    relevant += 1
            await mark_queue_status(ids, "done")
            processed += len(batch)
        except LlmError as exc:
            event(
                logger,
                "ЗАДАЧА",
                "Salary calib batch error: %s",
                exc,
                level=logging.WARNING,
                account_id=account_id,
                batch_size=len(batch),
            )
            await mark_queue_status(ids, "error", error=str(exc)[:500])
            errors += len(batch)
        except Exception as exc:  # noqa: BLE001 — один битый батч не валит весь разбор
            event(
                logger,
                "ЗАДАЧА",
                "Salary calib batch failed",
                level=logging.ERROR,
                exc_info=True,
                account_id=account_id,
                batch_size=len(batch),
            )
            await mark_queue_status(ids, "error", error=str(exc)[:500])
            errors += len(batch)

        batches_done += 1
        if on_progress:
            await on_progress(processed, relevant, errors)
        await asyncio.sleep(BATCH_PAUSE_SEC)

    return processed, relevant, errors


async def enqueue_if_salary_post(
    *,
    chat_id: int,
    message_id: int,
    text: str,
    account_id: int,
    forward_channel: str = "",
) -> tuple[bool, int]:
    """В очередь только посты с признаками вилки. Returns (accepted, queue_id)."""
    if not looks_like_salary_post(text):
        return False, 0
    qid, is_new = await enqueue_message(
        chat_id=chat_id,
        message_id=message_id,
        raw_text=text,
        account_id=account_id,
        forward_channel=forward_channel,
    )
    return is_new, qid


async def status_text(
    *,
    auto: bool = True,
    debounce_sec: float = 25.0,
    min_pending: int = 1,
) -> str:
    """Сводка очереди. Подсказки авто-разбора — с канала (бот), не из BotSettings."""
    pending, processing, done, err, samples, total_samples = await asyncio.gather(
        count_queue(status="pending"),
        count_queue(status="processing"),
        count_queue(status="done"),
        count_queue(status="error"),
        count_samples(relevant_only=True),
        count_samples(relevant_only=False),
    )
    lines = [
        f"Очередь: pending={pending}, processing={processing}, done={done}, error={err}",
        f"Образцы: релевантных={samples}, всего записей={total_samples}",
        "Сырой текст постов: salary_calibration_queue.raw_text",
        "Извлечение LLM: salary_calibration_samples (+ raw_excerpt 500 симв.)",
    ]
    if processing:
        lines.append(f"⚠️ {processing} в processing — ждите авто-разбор или /calib flush")
    if pending:
        if auto:
            lines.append(
                f"В очереди {pending}: авто-разбор через "
                f"~{debounce_sec:.0f} с "
                f"(нужно ≥{min_pending})"
            )
        else:
            lines.append(f"Осталось разобрать: {pending} pending (/calib flush)")
    return "\n".join(lines)


async def analyze_report(*, account_id: int) -> str:
    samples = await fetch_relevant_samples(account_id=account_id)
    return build_calibration_report(samples)
