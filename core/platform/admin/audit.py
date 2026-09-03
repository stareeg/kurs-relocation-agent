"""Реестр действий оператора: запись в `admin_audit` и чтение вкладки «Аудит».

Пишется рядом с событием `АДМИН` в `copilot_logs` (поток), но живёт отдельной таблицей:
поток нельзя спросить «кто скачал бандл логов Кати», а реестр — можно. Секреты
в `details` не кладём: маска ключа, не ключ.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from core.platform.admin.models import AdminAuditPage, AdminAuditRow, AdminError
from core.platform.db.pool import get_pool, row_to_dict
from core.platform.observability import event
from core.platform.openrouter_keys import mask_key

logger = logging.getLogger(__name__)

# Имена полей, которые нельзя класть в реестр даже «на всякий случай».
_SECRET_KEYS = frozenset(
    {"key", "raw_key", "api_key", "openrouter_api_key", "token", "secret", "password"}
)
_KEY_PREFIX = "sk-or-v1-"


def encode_cursor(ts: datetime, row_id: int) -> str:
    """Курсор страницы журнала/аудита: `{id}:{iso}`. id без двоеточий — режем по первому."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return f"{row_id}:{ts.isoformat()}"


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Разобрать курсор. Чужое значение — 400, а не 500: курсор живёт в URL."""
    raw = (cursor or "").strip()
    row_id_s, sep, ts_s = raw.partition(":")
    if not sep or not row_id_s.isdigit() or not ts_s:
        raise AdminError("Некорректный курсор журнала")
    try:
        ts = datetime.fromisoformat(ts_s)
    except ValueError as exc:
        raise AdminError("Некорректный курсор журнала") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts, int(row_id_s)


def sanitize_details(fields: dict[str, Any]) -> dict[str, Any]:
    """Убрать сырой ключ/секрет из jsonb аудита. Маска остаётся — по ней сверяют кабинет."""
    clean: dict[str, Any] = {}
    for name, value in fields.items():
        if name.lower() in _SECRET_KEYS:
            if isinstance(value, str) and value.strip():
                clean["key_hint"] = mask_key(value)
            continue
        if isinstance(value, str) and value.strip().startswith(_KEY_PREFIX):
            clean[name] = mask_key(value)
            continue
        clean[name] = value
    return clean


async def record(
    *,
    actor_id: int,
    action: str,
    target_id: int | None,
    details: dict[str, Any] | None = None,
) -> None:
    """Вставить строку реестра. Сбой записи не откатывает мутацию — только WARNING в лог."""
    payload = sanitize_details(details or {})
    try:
        await get_pool().execute(
            "insert into admin_audit (actor_id, action, target_id, details) "
            "values ($1, $2, $3, $4)",
            actor_id,
            action,
            target_id,
            payload,
        )
    except Exception as exc:
        event(
            logger,
            "АДМИН",
            "не удалось записать аудит action=%s target=%s: %s",
            action,
            target_id,
            exc,
            level=logging.WARNING,
            action=action,
            target_account_id=target_id,
            actor_account_id=actor_id,
            error=str(exc),
        )


def _audit_from_row(data: dict[str, Any]) -> AdminAuditRow:
    raw_details = data.get("details")
    details = raw_details if isinstance(raw_details, dict) else {}
    return AdminAuditRow(
        id=int(data["id"]),
        at=data.get("at"),
        actor_id=int(data["actor_id"]),
        actor_username=data.get("actor_username"),
        action=str(data.get("action") or ""),
        target_id=int(data["target_id"]) if data.get("target_id") is not None else None,
        target_username=data.get("target_username"),
        details=details,
    )


async def load_audit(
    *,
    since: datetime,
    until: datetime,
    target_id: int | None = None,
    telegram_user_id: int | None = None,
    cursor: tuple[datetime, int] | None = None,
    limit: int = 100,
) -> AdminAuditPage:
    """Страница реестра за окно. Курсор — (at, id), как у журнала логов."""
    conditions = ["a.at >= $1", "a.at < $2"]
    args: list[Any] = [since, until]
    if target_id is not None:
        args.append(target_id)
        conditions.append(f"a.target_id = ${len(args)}")
    if telegram_user_id is not None:
        args.append(telegram_user_id)
        conditions.append(
            f"(target.telegram_user_id = ${len(args)} or actor.telegram_user_id = ${len(args)})"
        )
    if cursor is not None:
        cursor_at, cursor_id = cursor
        args.extend([cursor_at, cursor_id])
        conditions.append(f"(a.at, a.id) < (${len(args) - 1}, ${len(args)})")
    args.append(limit + 1)
    sql = (
        "select a.id, a.at, a.actor_id, actor.telegram_username as actor_username, "
        "a.action, a.target_id, target.telegram_username as target_username, a.details "
        "from admin_audit a "
        "left join accounts actor on actor.id = a.actor_id "
        "left join accounts target on target.id = a.target_id "
        f"where {' and '.join(conditions)} "
        f"order by a.at desc, a.id desc limit ${len(args)}"
    )
    try:
        rows = [row_to_dict(r) for r in await get_pool().fetch(sql, *args)]
    except Exception as exc:
        event(
            logger,
            "АДМИН",
            "запрос аудита не ответил: %s",
            exc,
            level=logging.WARNING,
            error=str(exc),
        )
        return AdminAuditPage(
            items=[],
            since=since,
            until=until,
            degraded=True,
            degraded_reason="не отдали данные: аудит",
        )
    extra = rows[: limit + 1]
    page = extra[:limit]
    next_cursor = None
    if len(extra) > limit and page:
        last = page[-1]
        ts = last.get("at")
        if isinstance(ts, datetime):
            next_cursor = encode_cursor(ts, int(last["id"]))
    return AdminAuditPage(
        items=[_audit_from_row(r) for r in page],
        next_cursor=next_cursor,
        since=since,
        until=until,
    )


__all__ = [
    "decode_cursor",
    "encode_cursor",
    "load_audit",
    "record",
    "sanitize_details",
]
