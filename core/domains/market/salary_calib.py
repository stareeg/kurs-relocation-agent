"""Персистентность калибровки зарплат: очередь пересланных постов + извлечённые вилки.

content_hash дедуплицирует одинаковые посты; (chat_id, message_id) unique — повтор пересылки
не плодит очередь. Sessions/meta — служебное состояние режима калибровки.

M5 (plans/multitenancy_gaps_2026_08_06.md §9 п.1): очередь/сессии де-факто изолированы по
`chat_id` (один Telegram-чат = один аккаунт) — `account_id` на них для FK/единообразия и будущего
RLS, чтение остаётся по `chat_id`, как раньше. `samples`/`meta` — решение владельца: личные
наблюдения аккаунта, не общий корпус; `samples.account_id` денормализован от очереди (queue_id →
account_id), `meta` получает составной ключ `(account_id, key)`.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from pydantic import BaseModel

from core.platform.db.pool import Executor, get_pool, row_to_dict

_QUEUE_COLS = (
    "id, account_id, chat_id, message_id, raw_text, forward_channel, status, error, "
    "content_hash, created_at, processed_at"
)
# Колонки = существующая 0003-таблица (legacy_id из истории Задача 1.3) + queue_id (S9 pipeline)
# + source/content_hash (воронка как источник сэмплов наравне с forwarded-постами).
_SAMPLE_COLS = (
    "id, account_id, legacy_id, queue_id, is_relevant, skip_reason, company, position, grade, "
    "company_type, salary_min_net, salary_max_net, salary_scale, bonus_text, bonus_type, city, "
    "work_format, source_channel, confidence, note, raw_excerpt, source, content_hash, created_at"
)
# Статусы очереди, при которых пост считается уже принятым (дедуп по content_hash).
_ACTIVE_STATUSES = ("pending", "processing", "done")


class CalibQueueItem(BaseModel):
    id: int | None = None
    account_id: int
    chat_id: int
    message_id: int
    raw_text: str
    forward_channel: str = ""
    status: str = "pending"
    error: str = ""
    content_hash: str = ""
    created_at: datetime | None = None
    processed_at: datetime | None = None


class CalibSample(BaseModel):
    """Сэмпл калибровки — личное наблюдение аккаунта (план §9 п.1). Поля nullable как в 0003
    (историч. строки могут иметь NULL-текст).

    `legacy_id` — id из SQLite-истории (Задача 1.3), NULL у новых сэмплов из пайплайна;
    `queue_id` — ссылка на очередь (S9), NULL у историч. строк.
    """

    id: int | None = None
    account_id: int
    legacy_id: int | None = None
    queue_id: int | None = None
    is_relevant: bool = True
    skip_reason: str | None = None
    company: str | None = None
    position: str | None = None
    grade: str | None = None
    company_type: str | None = None
    salary_min_net: int | None = None
    salary_max_net: int | None = None
    salary_scale: str | None = None
    bonus_text: str | None = None
    bonus_type: str | None = None
    city: str | None = None
    work_format: str | None = None
    source_channel: str | None = None
    confidence: str | None = None
    note: str | None = None
    raw_excerpt: str | None = None
    # JS-8.2: 'forwarded' — пересланный в бот пост; 'funnel' — факт воронки (HR-вилка/оффер).
    source: str = "forwarded"
    content_hash: str = ""
    created_at: datetime | None = None


def text_fingerprint(raw_text: str) -> str:
    """Нормализованный хеш текста поста (дедуп одинаковых вакансий)."""
    t = re.sub(r"\s+", " ", (raw_text or "").strip().lower())[:4000]
    return hashlib.sha256(t.encode("utf-8")).hexdigest()[:32]


# ---- sessions / meta ----


async def set_session_active(
    chat_id: int, *, active: bool, account_id: int | None = None, db: Executor | None = None
) -> None:
    """`account_id` обязателен при `active=True` (запись строки); при выключении не нужен —
    `delete` идёт по `chat_id`."""
    db = db or get_pool()
    if active:
        if account_id is None:
            raise ValueError("account_id required to enable a session")
        await db.execute(
            "insert into salary_calibration_sessions (chat_id, account_id, enabled_at) "
            "values ($1, $2, now()) "
            "on conflict (chat_id) do update set "
            "account_id = excluded.account_id, enabled_at = excluded.enabled_at",
            chat_id,
            account_id,
        )
    else:
        await db.execute("delete from salary_calibration_sessions where chat_id = $1", chat_id)


async def list_active_sessions(*, db: Executor | None = None) -> list[int]:
    """Все активные чаты (де-факто изолированы по `chat_id`) — системный воркер, не личный вид."""
    db = db or get_pool()
    rows = await db.fetch("select chat_id from salary_calibration_sessions order by chat_id")
    return [int(r["chat_id"]) for r in rows]


async def get_meta(
    key: str, default: str = "", *, account_id: int, db: Executor | None = None
) -> str:
    db = db or get_pool()
    val = await db.fetchval(
        "select value from salary_calibration_meta where account_id = $1 and key = $2",
        account_id,
        key,
    )
    return str(val) if val is not None else default


async def set_meta(key: str, value: str, *, account_id: int, db: Executor | None = None) -> None:
    db = db or get_pool()
    await db.execute(
        "insert into salary_calibration_meta (account_id, key, value) values ($1, $2, $3) "
        "on conflict (account_id, key) do update set value = excluded.value",
        account_id,
        key,
        value,
    )


# ---- queue ----


async def find_by_content_hash(
    content_hash: str, *, db: Executor | None = None
) -> tuple[int, str] | None:
    """Вернуть (queue_id, status) если такой текст уже был (последний по id)."""
    db = db or get_pool()
    row = await db.fetchrow(
        "select id, status from salary_calibration_queue where content_hash = $1 "
        "order by id desc limit 1",
        content_hash,
    )
    return (int(row["id"]), str(row["status"])) if row else None


async def enqueue_message(
    *,
    chat_id: int,
    message_id: int,
    raw_text: str,
    account_id: int,
    forward_channel: str = "",
    db: Executor | None = None,
) -> tuple[int, bool]:
    """Вернуть (queue_id, is_new).

    Повтор того же текста/сообщения не дублирует очередь. `account_id` — кто
    переслал (атрибуция сэмпла, извлечённого пайплайном из этой строки).
    """
    db = db or get_pool()
    content_hash = text_fingerprint(raw_text)
    dup = await find_by_content_hash(content_hash, db=db)
    if dup and dup[1] in _ACTIVE_STATUSES:
        return dup[0], False

    row = await db.fetchrow(
        "insert into salary_calibration_queue "
        "(chat_id, message_id, raw_text, forward_channel, content_hash, status, account_id) "
        "values ($1, $2, $3, $4, $5, 'pending', $6) "
        "on conflict (chat_id, message_id) do nothing returning id",
        chat_id,
        message_id,
        raw_text,
        forward_channel,
        content_hash,
        account_id,
    )
    if row:
        return int(row["id"]), True
    existing = await db.fetchval(
        "select id from salary_calibration_queue where chat_id = $1 and message_id = $2",
        chat_id,
        message_id,
    )
    if existing is None:
        raise RuntimeError(
            f"salary_calibration_queue: insert conflict без id (chat={chat_id}, msg={message_id})"
        )
    return int(existing), False


async def count_queue(*, status: str | None = None, db: Executor | None = None) -> int:
    db = db or get_pool()
    if status:
        val = await db.fetchval(
            "select count(*) from salary_calibration_queue where status = $1", status
        )
    else:
        val = await db.fetchval("select count(*) from salary_calibration_queue")
    return int(val or 0)


async def requeue_processing(*, db: Executor | None = None) -> int:
    """Зависшие processing → pending (после рестарта бота или сбоя). Возвращает число строк."""
    db = db or get_pool()
    rows = await db.fetch(
        "update salary_calibration_queue set status = 'pending', error = '', processed_at = null "
        "where status = 'processing' returning id"
    )
    return len(rows)


async def fetch_pending_batch(
    limit: int = 12, *, db: Executor | None = None
) -> list[CalibQueueItem]:
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_QUEUE_COLS} from salary_calibration_queue where status = 'pending' "
        "order by id asc limit $1",
        limit,
    )
    return [CalibQueueItem(**row_to_dict(r)) for r in rows]


async def mark_queue_status(
    queue_ids: list[int],
    status: str,
    *,
    error: str = "",
    db: Executor | None = None,
) -> None:
    if not queue_ids:
        return
    db = db or get_pool()
    await db.execute(
        "update salary_calibration_queue set status = $1, error = $2, processed_at = now() "
        "where id = any($3::bigint[])",
        status,
        error,
        queue_ids,
    )


async def retry_error_queue(*, max_items: int = 50, db: Executor | None = None) -> int:
    """error → pending для повторной обработки. Возвращает число строк."""
    db = db or get_pool()
    rows = await db.fetch(
        "update salary_calibration_queue set status = 'pending', error = '', processed_at = null "
        "where id in (select id from salary_calibration_queue where status = 'error' "
        "order by id asc limit $1) returning id",
        max_items,
    )
    return len(rows)


# ---- samples ----


async def insert_sample(sample: CalibSample, *, db: Executor | None = None) -> int:
    """Вставить извлечённую вилку под `sample.account_id` (личное наблюдение аккаунта).

    Возвращает id вставленной строки.
    """
    db = db or get_pool()
    val = await db.fetchval(
        "insert into salary_calibration_samples "
        "(account_id, queue_id, is_relevant, skip_reason, company, position, grade, company_type, "
        "salary_min_net, salary_max_net, salary_scale, bonus_text, bonus_type, city, "
        "work_format, source_channel, confidence, note, raw_excerpt, source, content_hash) "
        "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21) "
        "returning id",
        sample.account_id,
        sample.queue_id,
        sample.is_relevant,
        sample.skip_reason,
        sample.company,
        sample.position,
        sample.grade,
        sample.company_type,
        sample.salary_min_net,
        sample.salary_max_net,
        sample.salary_scale,
        sample.bonus_text,
        sample.bonus_type,
        sample.city,
        sample.work_format,
        sample.source_channel,
        sample.confidence,
        sample.note,
        sample.raw_excerpt,
        sample.source,
        sample.content_hash,
    )
    if val is None:
        raise RuntimeError("salary_calibration_samples: insert не вернул id")
    return int(val)


async def insert_funnel_sample(sample: CalibSample, *, db: Executor | None = None) -> int | None:
    """Вставить сэмпл из воронки (HR-вилка/оффер) с дедупом по content_hash.

    Уже есть funnel-сэмпл с тем же content_hash у ЭТОГО аккаунта → ничего не пишем, возвращаем
    None (фоновый HR-пересчёт и повторные правки оффера не плодят дубли). content_hash обязателен.
    """
    if not sample.content_hash:
        raise ValueError("content_hash required for funnel sample")
    db = db or get_pool()
    sample = sample.model_copy(update={"source": "funnel"})
    if await funnel_sample_present(sample.content_hash, account_id=sample.account_id, db=db):
        return None
    return await insert_sample(sample, db=db)


async def funnel_sample_present(
    content_hash: str, *, account_id: int, db: Executor | None = None
) -> bool:
    """Есть ли уже funnel-сэмпл аккаунта с таким content_hash (дедуп JS-8.2, личный — не общий)."""
    if not content_hash:
        return False
    db = db or get_pool()
    val = await db.fetchval(
        "select 1 from salary_calibration_samples "
        "where account_id = $1 and source = 'funnel' and content_hash = $2 limit 1",
        account_id,
        content_hash,
    )
    return val is not None


async def count_samples(*, relevant_only: bool = True, db: Executor | None = None) -> int:
    """Счёт по всему пайплайну (системная операторская сводка `/calib status`, не личный вид)."""
    db = db or get_pool()
    if relevant_only:
        val = await db.fetchval(
            "select count(*) from salary_calibration_samples where is_relevant = true"
        )
    else:
        val = await db.fetchval("select count(*) from salary_calibration_samples")
    return int(val or 0)


async def fetch_relevant_samples(
    limit: int = 5000, *, account_id: int, db: Executor | None = None
) -> list[CalibSample]:
    """Релевантные сэмплы аккаунта с заполненной нижней вилкой (для анализа калибровки)."""
    db = db or get_pool()
    rows = await db.fetch(
        f"select {_SAMPLE_COLS} from salary_calibration_samples "
        "where account_id = $1 and is_relevant = true and salary_min_net is not null "
        "order by id desc limit $2",
        account_id,
        limit,
    )
    return [CalibSample(**row_to_dict(r)) for r in rows]
