"""Pending HR-кнопок: resolve confirmation + «Указать @HR» (/ B7).

Раньше — in-memory TTL 1ч: рестарт бота = «Запрос устарел». Теперь Postgres
`tg_hr_pending` (токен → payload jsonb), TTL сутки. In-memory кэш write-through:
тот же процесс не ходит в PG на каждый get; при падении PG кнопки живы до рестарта.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from core.domains.pipeline.models import HrMessageAnalysis
from core.platform.db.pool import Executor, get_pool

logger = logging.getLogger(__name__)

# TB-7.3: сутки (было 1ч in-memory) — владелец может вернуться к кнопке на следующий день.
_TTL = timedelta(days=1)
_TTL_SEC = _TTL.total_seconds()


@dataclass
class PendingHrContext:
    analysis: HrMessageAnalysis
    pending_resolve_vacancy_id: str = ""
    telegram_msg_id: int = 0
    chat_id: int = 0
    created_at: float = field(default_factory=time.time)
    # Этап 3: сверяется с account_id аргумента get/pop даже на in-memory fast-path (ниже) —
    # без этого поля токен, случайно совпавший в _MEM другого процесса/аккаунта, обошёл бы
    # фильтр account_id, который есть в DB-пути.
    account_id: int = 0


_MEM: dict[str, PendingHrContext] = {}


def _expired(ctx: PendingHrContext, *, now: float | None = None) -> bool:
    ts = now if now is not None else time.time()
    return (ts - ctx.created_at) > _TTL_SEC


def _payload_from_ctx(ctx: PendingHrContext) -> dict[str, Any]:
    return {
        "analysis": ctx.analysis.model_dump(mode="json"),
        "pending_resolve_vacancy_id": ctx.pending_resolve_vacancy_id,
        "telegram_msg_id": ctx.telegram_msg_id,
        "chat_id": ctx.chat_id,
        "created_at": ctx.created_at,
        "account_id": ctx.account_id,
    }


def _ctx_from_payload(payload: dict[str, Any]) -> PendingHrContext | None:
    try:
        raw_analysis = payload.get("analysis") or {}
        analysis = HrMessageAnalysis.model_validate(raw_analysis)
        return PendingHrContext(
            analysis=analysis,
            pending_resolve_vacancy_id=str(payload.get("pending_resolve_vacancy_id") or ""),
            telegram_msg_id=int(payload.get("telegram_msg_id") or 0),
            chat_id=int(payload.get("chat_id") or 0),
            created_at=float(payload.get("created_at") or time.time()),
            account_id=int(payload.get("account_id") or 0),
        )
    except Exception as exc:  # noqa: BLE001 — битый jsonb не валит хендлер
        logger.warning("tg_hr_pending: не разобрать payload: %s", exc)
        return None


def _mem_gc(*, now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    expired = [k for k, v in _MEM.items() if _expired(v, now=ts)]
    for k in expired:
        _MEM.pop(k, None)


async def expire_due(*, db: Executor | None = None) -> int:
    """Удалить просроченные строки (cron tg_cleanup). Число удалённых."""
    try:
        pool = db or get_pool()
        rows = await pool.fetch(
            "delete from tg_hr_pending where expires_at <= now() returning token"
        )
        for row in rows:
            _MEM.pop(str(row["token"]), None)
        return len(rows)
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.debug("tg_hr_pending expire_due failed: %s", exc)
        return 0


async def save(ctx: PendingHrContext, *, account_id: int, db: Executor | None = None) -> str:
    """Сохранить контекст, вернуть короткий token для callback_data."""
    _mem_gc()
    ctx.account_id = account_id
    token = secrets.token_urlsafe(8)
    created = datetime.fromtimestamp(ctx.created_at, tz=UTC)
    expires = created + _TTL
    payload = _payload_from_ctx(ctx)
    _MEM[token] = ctx

    try:
        pool = db or get_pool()
        await pool.execute(
            """
            insert into tg_hr_pending (token, chat_id, payload, created_at, expires_at, account_id)
            values ($1, $2, $3::jsonb, $4, $5, $6)
            on conflict (token) do update set
                chat_id = excluded.chat_id,
                payload = excluded.payload,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at
            """,
            token,
            ctx.chat_id,
            payload,
            created,
            expires,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001 — in-memory хватит до рестарта
        logger.debug("tg_hr_pending save failed token=%s: %s", token, exc)

    return token


async def get(
    token: str, *, account_id: int, db: Executor | None = None
) -> PendingHrContext | None:
    """Прочитать контекст по токену (без удаления). None если нет / просрочен / чужой аккаунт."""
    if not token:
        return None
    _mem_gc()
    cached = _MEM.get(token)
    if cached is not None:
        if _expired(cached) or cached.account_id != account_id:
            _MEM.pop(token, None)
        else:
            return cached

    try:
        pool = db or get_pool()
        row = await pool.fetchrow(
            """
            select payload, expires_at from tg_hr_pending
            where token = $1 and account_id = $2
            """,
            token,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("tg_hr_pending get failed token=%s: %s", token, exc)
        return None

    if row is None:
        return None

    expires_at = row["expires_at"]
    if expires_at is not None:
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
        if exp <= datetime.now(UTC):
            await pop(token, account_id=account_id, db=db)
            return None

    payload = row["payload"]
    if not isinstance(payload, dict):
        return None
    ctx = _ctx_from_payload(payload)
    if ctx is None or _expired(ctx):
        await pop(token, account_id=account_id, db=db)
        return None
    _MEM[token] = ctx
    return ctx


async def put(
    token: str, ctx: PendingHrContext, *, account_id: int, db: Executor | None = None
) -> bool:
    """Обновить payload существующего токена (после ручного @HR)."""
    if not token:
        return False
    ctx.account_id = account_id
    _MEM[token] = ctx
    created = datetime.fromtimestamp(ctx.created_at, tz=UTC)
    expires = created + _TTL
    payload = _payload_from_ctx(ctx)
    try:
        pool = db or get_pool()
        await pool.execute(
            """
            update tg_hr_pending
            set chat_id = $2, payload = $3::jsonb, expires_at = $4
            where token = $1 and account_id = $5 and expires_at > now()
            """,
            token,
            ctx.chat_id,
            payload,
            expires,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("tg_hr_pending put failed token=%s: %s", token, exc)
    return True


async def pop(
    token: str, *, account_id: int, db: Executor | None = None
) -> PendingHrContext | None:
    """Удалить и вернуть контекст. None если нет / просрочен / чужой аккаунт."""
    if not token:
        return None
    _mem_gc()
    cached = _MEM.pop(token, None)

    try:
        pool = db or get_pool()
        row = await pool.fetchrow(
            """
            delete from tg_hr_pending
            where token = $1 and account_id = $2
            returning payload, expires_at
            """,
            token,
            account_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("tg_hr_pending pop failed token=%s: %s", token, exc)
        if cached is not None and not _expired(cached) and cached.account_id == account_id:
            return cached
        return None

    if row is None:
        if cached is not None and not _expired(cached) and cached.account_id == account_id:
            return cached
        return None

    expires_at = row["expires_at"]
    if expires_at is not None:
        exp = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=UTC)
        if exp <= datetime.now(UTC):
            return None

    payload = row["payload"]
    if isinstance(payload, dict):
        ctx = _ctx_from_payload(payload)
        if ctx is not None and not _expired(ctx):
            return ctx
    if cached is not None and not _expired(cached) and cached.account_id == account_id:
        return cached
    return None


def clear_memory() -> None:
    """Сброс in-memory кэша (тесты)."""
    _MEM.clear()


__all__ = [
    "PendingHrContext",
    "clear_memory",
    "expire_due",
    "get",
    "pop",
    "put",
    "save",
]
