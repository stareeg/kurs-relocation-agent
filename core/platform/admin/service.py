"""Сводка флота и мутации аккаунтов. Запросы мимо RLS (`get_pool()`), как accounts-repo."""

from __future__ import annotations

import json
import logging
import os
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.config import get_settings
from core.platform import openrouter_keys
from core.platform.admin.audit import (
    decode_cursor,
    encode_cursor,
    load_audit,
    sanitize_details,
)
from core.platform.admin.audit import record as record_audit
from core.platform.admin.diagnosis import facts_from_user
from core.platform.admin.models import (
    AdminAccountSnapshot,
    AdminAttention,
    AdminAuditPage,
    AdminAuditRow,
    AdminDeviceSession,
    AdminDiagnosis,
    AdminError,
    AdminErrorBurst,
    AdminHealth,
    AdminHealthQueue,
    AdminKeyBalance,
    AdminKeyBalances,
    AdminKeyHistory,
    AdminKeyRequest,
    AdminKeyVerify,
    AdminLogPage,
    AdminLogRow,
    AdminNoKeyWait,
    AdminOnboardingFunnel,
    AdminPeoplePage,
    AdminPipelineBrief,
    AdminPipelinePlatform,
    AdminRecentAction,
    AdminSpend,
    AdminSpendOver,
    AdminSpendRow,
    AdminSpendSegment,
    AdminStaleAccount,
    AdminSummary,
    AdminSupportMessage,
    AdminSupportThread,
    AdminTables,
    AdminTableSize,
    AdminTaskDetail,
    AdminTaskKindCount,
    AdminTaskReasonCount,
    AdminTaskRow,
    AdminTasks,
    AdminTelegramSent,
    AdminUserDetail,
    AdminUserPipeline,
    AdminUserRow,
    FunnelCounts,
)
from core.platform.db.migrate import migration_numbers
from core.platform.db.pool import get_pool, row_to_dict
from core.platform.observability import event
from core.platform.openrouter_keys import OpenRouterKeyError, mask_key
from core.platform.repo.accounts import (
    Role,
    disable_account,
    enable_account,
    get_account_by_id,
    list_active_accounts,
    set_account_note,
    set_account_role,
)
from core.platform.repo.log_bundle import build_log_bundle_zip
from core.platform.repo.settings import set_setting
from core.platform.tasks import enqueue, get_runtime
from core.platform.tasks.models import TaskRecord
from core.platform.tasks.store import TASK_REASON_LEN

logger = logging.getLogger(__name__)

_USERS_SQL_BODY = """
select
    a.id as account_id,
    a.telegram_username,
    a.telegram_user_id,
    a.telegram_chat_id,
    a.role,
    a.status,
    a.created_at,
    a.last_seen_at,
    a.last_seen_ip,
    a.note,
    a.disabled_at,
    a.disabled_reason,
    exists(select 1 from resumes r where r.account_id = a.id) as has_resume,
    exists(
        select 1 from account_settings s
        where s.account_id = a.id and s.key = 'openrouter_api_key'
          and jsonb_typeof(s.value) = 'string'
          and length(trim(s.value #>> '{}')) > 0
    ) as has_openrouter_key,
    coalesce((
        select (s.value->>'extension_confirmed')::boolean
        from account_settings s
        where s.account_id = a.id and s.key = 'onboarding'
    ), false) as extension_confirmed,
    -- Живая воронка, а не весь архив: оператору интересно, чем человек занят сейчас.
    -- Архивные и пропущенные не считаем осознанно (Этап 0.1 плана админки) — не «чинить»
    -- обратно на count(*), подпись колонки обещает именно активные.
    coalesce((
        select count(*)::int from jobs j
        where j.account_id = a.id
          and not j.is_archived
          and coalesce(j.status, '') <> 'skipped'
    ), 0) as active_jobs,
    coalesce((
        select sum(u.cost_usd)::float8 from llm_usage u
        where u.account_id = a.id and u.day = current_date
    ), 0) as today_cost_usd,
    coalesce((
        select count(*)::int from copilot_logs l
        where l.account_id = a.id
          and l.ts >= now() - interval '24 hours'
          and l.level in ('ERROR', 'CRITICAL')
    ), 0) as errors_24h,
    coalesce((
        select count(*)::int from account_sessions sess
        where sess.account_id = a.id and sess.revoked_at is null
    ), 0) as session_count,
    k.origin as key_origin,
    k.key_hint as key_hint,
    k.label as key_label,
    k.issued_at as key_issued_at,
    k.updated_at as key_updated_at,
    coalesce((
        select sum(u.cost_usd)::float8 from llm_usage u
        where u.account_id = a.id and u.day >= current_date - 29
    ), 0) as month_cost_usd,
    -- Календарный месяц — окно мягкого лимита (Этап 8.2), то же, что «за месяц» на Обзоре.
    -- Не подменять скользящими 30 днями: порог тогда срабатывал бы за чужой месяц.
    coalesce((
        select sum(u.cost_usd)::float8 from llm_usage u
        where u.account_id = a.id
          and u.day >= date_trunc('month', current_date)::date
    ), 0) as spend_month_usd,
    coalesce((
        select sum(u.tokens_in)::bigint from llm_usage u
        where u.account_id = a.id and u.day >= current_date - 29
    ), 0) as month_tokens_in,
    coalesce((
        select sum(u.tokens_out)::bigint from llm_usage u
        where u.account_id = a.id and u.day >= current_date - 29
    ), 0) as month_tokens_out
from accounts a
left join openrouter_account_keys k on k.account_id = a.id
"""

# Операторы сверху, под ними новые люди (created_at desc), активные раньше отключённых.
_DEFAULT_PEOPLE_ORDER = (
    "case when p.role = 'owner' then 0 else 1 end, "
    "p.status asc, p.created_at desc nulls last, p.account_id"
)
_USER_BY_ID_SQL = f"{_USERS_SQL_BODY}where a.id = $1"

# Сортировки и фильтры списка людей — по белым спискам, а не по строке из query: значения
# подставляются в SQL текстом, параметризовать имя колонки нельзя. Ключи — то, что уходит
# в URL (`?sort=-cost_month`), поэтому переименование ключа ломает сохранённую ссылку.
_PEOPLE_SORT_COLUMNS: dict[str, str] = {
    "last_seen": "p.last_seen_at",
    "created": "p.created_at",
    "username": "p.telegram_username",
    "jobs": "p.active_jobs",
    "cost_today": "p.today_cost_usd",
    "cost_month": "p.month_cost_usd",
    "errors": "p.errors_24h",
    "status": "p.status",
}

_PEOPLE_ONBOARDING_FILTERS: dict[str, str] = {
    "no_key": "not p.has_openrouter_key",
    "no_resume": "not p.has_resume",
    "no_extension": "not p.extension_confirmed",
    "done": "p.has_openrouter_key and p.has_resume and p.extension_confirmed",
}

# «Есть ошибки» / «молчат > 7 дней» — отдельные чипы, не ступени онбординга: их можно
# сочетать с status и onboarding. Значения уходят в URL (`?signal=stale`).
# `spend` — динамический: порог приезжает параметром, в фрагмент его не зашить.
_PEOPLE_SIGNAL_FILTERS: dict[str, str] = {
    "errors": "p.errors_24h > 0",
    "stale": "(p.last_seen_at is null or p.last_seen_at < now() - interval '7 days')",
}
_PEOPLE_SIGNALS = frozenset({*_PEOPLE_SIGNAL_FILTERS, "spend"})

# Мягкий лимит: ключ app_settings, 0 = сигнал выключен. Жёсткой отсечки в этом этапе нет.
SPEND_ALERT_KEY = "admin_spend_alert_usd"
SPEND_ALERT_MAX_USD = 10_000.0

_PEOPLE_STATUS_VALUES = frozenset({"active", "disabled"})
SPEND_SPARKLINE_DAYS = 14

# Корень репо: service.py → admin → platform → core → repo. Тот же путь, что у meta.py
# к `extension/manifest.json` — канон версии расширения, без импорта api-слоя.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Тот же критерий «ключ есть», что в `_USERS_SQL_BODY`: иначе воронка и таблица людей
# разойдутся, и клик по ступени откроет не тех, кого показывал счётчик.
_HAS_OPENROUTER_KEY_SQL = (
    "exists("
    "select 1 from account_settings s "
    "where s.account_id = a.id and s.key = 'openrouter_api_key' "
    "  and jsonb_typeof(s.value) = 'string' "
    "  and length(trim(s.value #>> '{}')) > 0"
    ")"
)
_HAS_RESUME_SQL = "exists(select 1 from resumes r where r.account_id = a.id)"
_EXTENSION_CONFIRMED_SQL = (
    "coalesce(("
    "select (s.value->>'extension_confirmed')::boolean "
    "from account_settings s "
    "where s.account_id = a.id and s.key = 'onboarding'"
    "), false)"
)

# Журнал (Этап 5): жёсткие ограничители, чтобы выборка не превратилась в seq-scan по
# всей вечной таблице copilot_logs. limit и окно режутся здесь, не в FastAPI, — одна
# правда для ручки и для «копировать как SQL».
MAX_LOG_LIMIT = 200
DEFAULT_LOG_LIMIT = 100
MAX_LOG_WINDOW = timedelta(days=14)
DEFAULT_LOG_WINDOW = timedelta(hours=1)
MIN_LOG_QUERY_LEN = 3
LOG_STATEMENT_TIMEOUT = "8s"
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
DEFAULT_LOG_LEVELS: tuple[str, ...] = ("ERROR", "WARNING")

# Очередь (Этап 7): статус и kind в SQL параметрами, limit режется здесь.
TASK_STATUS_VALUES = frozenset({"pending", "running", "failed", "done", "cancelled"})
MAX_TASK_LIMIT = 200
DEFAULT_TASK_LIMIT = 40
# Раздел «Действия»: старше окна оператору не нужно — иначе «Все» тянет годы done.
TASK_WINDOW_HOURS = 48
LOG_PURGE_DAYS = frozenset({30, 60, 90})

# Ключевые таблицы для «сколько занимает»: растут без cron, оператору нужно видеть, что раздулось.
_TABLE_SIZE_NAMES: tuple[str, ...] = (
    "copilot_logs",
    "llm_usage",
    "llm_result_cache",
    "jobs",
    "background_tasks",
    "accounts",
    "account_sessions",
    "resumes",
    "admin_audit",
    "openrouter_key_requests",
    "openrouter_account_keys",
    "career_facts",
    "career_timeline",
)

# Разрезы расхода: выражение ключа + порядок. День — по убыванию (последняя дата сверху
# в таблице и слева на графике), остальные — по убыванию денег.
_SPEND_GROUPS: dict[str, tuple[str, str]] = {
    "day": ("u.day::text", "1 desc"),
    "model": ("coalesce(nullif(u.model, ''), 'без модели')", "cost_usd desc"),
    "feature": ("coalesce(nullif(u.agent, ''), 'без фичи')", "cost_usd desc"),
    "account": (
        "coalesce(a.telegram_username, case when u.account_id is null then 'система' "
        "else 'id ' || u.account_id::text end)",
        "cost_usd desc",
    ),
}

# Общие агрегаты строки разреза. count(u.id) — не count(*): разрез по дням left join'ит
# пустые даты, и звёздочка превратила бы дырку в один фейковый вызов.
_SPEND_ROW_AGG = """
coalesce(sum(u.cost_usd), 0)::float8 as cost_usd,
coalesce(sum(u.tokens_in), 0)::bigint as tokens_in,
coalesce(sum(u.tokens_out), 0)::bigint as tokens_out,
count(u.id)::int as calls,
count(u.id) filter (where u.cache_hit)::int as cache_hits,
percentile_cont(0.5) within group (order by u.total_ms)
  filter (where u.total_ms is not null) as median_ms,
percentile_cont(0.95) within group (order by u.total_ms)
  filter (where u.total_ms is not null) as p95_ms,
count(u.id) filter (where coalesce(u.attempt, 1) > 1)::int as retries
"""


def people_sort_keys() -> list[str]:
    """Допустимые значения `sort` вместе с направлением — для валидации и для тестов."""
    return [k for key in _PEOPLE_SORT_COLUMNS for k in (key, f"-{key}")]


async def _log_action(
    action: str, actor_id: int, *, target_account_id: int | None = None, **fields: Any
) -> None:
    """Пишет и в поток `АДМИН` (copilot_logs), и в реестр `admin_audit` (Этап 5.4).

    `target_account_id` пуст у действий на установку: уборка логов, reclaim, ремонт дружб.
    """
    details = sanitize_details(fields)
    event(
        logger,
        "АДМИН",
        "action=%s target=%s",
        action,
        target_account_id,
        action=action,
        target_account_id=target_account_id,
        actor_account_id=actor_id,
        **details,
    )
    await record_audit(
        actor_id=actor_id,
        action=action,
        target_id=target_account_id,
        details=details,
    )


def _user_from_row(data: dict[str, Any]) -> AdminUserRow:
    return AdminUserRow(
        account_id=int(data["account_id"]),
        telegram_username=data.get("telegram_username"),
        telegram_user_id=int(data["telegram_user_id"]),
        role=str(data.get("role") or "member"),
        status=str(data.get("status") or "active"),
        created_at=data.get("created_at"),
        last_seen_at=data.get("last_seen_at"),
        last_seen_ip=data.get("last_seen_ip"),
        has_resume=bool(data.get("has_resume")),
        has_openrouter_key=bool(data.get("has_openrouter_key")),
        extension_confirmed=bool(data.get("extension_confirmed")),
        active_jobs=int(data.get("active_jobs") or 0),
        today_cost_usd=float(data.get("today_cost_usd") or 0.0),
        errors_24h=int(data.get("errors_24h") or 0),
        session_count=int(data.get("session_count") or 0),
        telegram_chat_id=data.get("telegram_chat_id"),
        # Строки openrouter_account_keys нет, а ключ есть — наследие до 0141: считаем своим,
        # ровно как решил бэкфилл миграции (у человека ключ на руках).
        key_origin=(
            str(data.get("key_origin") or "self") if data.get("has_openrouter_key") else None
        ),
        key_hint=str(data.get("key_hint") or ""),
        key_label=data.get("key_label"),
        key_issued_at=data.get("key_issued_at"),
        key_updated_at=data.get("key_updated_at") or data.get("key_issued_at"),
        month_cost_usd=float(data.get("month_cost_usd") or 0.0),
        month_tokens_in=int(data.get("month_tokens_in") or 0),
        month_tokens_out=int(data.get("month_tokens_out") or 0),
        spend_month_usd=float(data.get("spend_month_usd") or 0.0),
        spend_alert=bool(data.get("spend_alert")),
        spend_14d=[float(v) for v in (data.get("spend_14d") or [])],
        note=(str(data["note"]).strip() or None) if data.get("note") else None,
        disabled_at=data.get("disabled_at"),
        disabled_reason=(
            str(data["disabled_reason"]).strip() or None if data.get("disabled_reason") else None
        ),
    )


def search_profile_lines(resume: Any) -> tuple[str, str, str]:
    """Должность / грейд / формат из jsonb резюме — без импорта домена profile."""
    data = resume
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return "", "", ""
    if not isinstance(data, dict):
        return "", "", ""
    position = data.get("position")
    if not isinstance(position, dict):
        return "", "", ""
    title = str(position.get("title") or "").strip()
    grades = _as_str_list(position.get("grade"))
    formats = _as_str_list(position.get("schedule"))
    return title, ", ".join(grades), ", ".join(formats)


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _salary_override(raw: Any) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def _any_platform_enabled(raw: Any) -> bool:
    """Автоотклик и discovery хранятся по площадкам, общего `enabled` нет."""
    if not isinstance(raw, dict):
        return False
    if raw.get("enabled") is True:
        return True
    return any(
        isinstance(raw.get(name), dict) and raw[name].get("enabled") is True
        for name in ("hh", "getmatch", "habr")
    )


def _runner_tick_at(raw: Any) -> datetime | None:
    """`{at, summary, logged_at}` heartbeat раннера расширения → datetime поля `at`."""
    if not isinstance(raw, dict):
        return None
    stamp = raw.get("at")
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _key_request_from_row(data: dict[str, Any]) -> AdminKeyRequest:
    resolved_by = data.get("resolved_by")
    return AdminKeyRequest(
        id=int(data["id"]),
        account_id=int(data["account_id"]),
        telegram_username=data.get("telegram_username"),
        status=str(data.get("status") or ""),
        requested_at=data.get("requested_at"),
        note=data.get("note"),
        resolved_at=data.get("resolved_at"),
        resolved_by=int(resolved_by) if resolved_by is not None else None,
        resolver_username=data.get("resolver_username"),
    )


def _key_verify_from_probe(probe: openrouter_keys.KeyProbe) -> AdminKeyVerify:
    return AdminKeyVerify(
        alive=probe.alive,
        network_error=probe.network_error,
        error=probe.error,
        key_hint=probe.key_hint,
        label=probe.label,
        limit=probe.limit,
        usage=probe.usage,
        limit_remaining=probe.limit_remaining,
        is_free_tier=probe.is_free_tier,
    )


def _audit_row_from_row(data: dict[str, Any]) -> AdminAuditRow:
    raw_details = data.get("details")
    details = raw_details if isinstance(raw_details, dict) else {}
    target_id = data.get("target_id")
    return AdminAuditRow(
        id=int(data["id"]),
        at=data.get("at"),
        actor_id=int(data["actor_id"]),
        actor_username=data.get("actor_username"),
        action=str(data.get("action") or ""),
        target_id=int(target_id) if target_id is not None else None,
        target_username=data.get("target_username"),
        details=details,
    )


def _task_from_row(data: dict[str, Any]) -> AdminTaskRow:
    return AdminTaskRow(
        id=int(data["id"]),
        kind=str(data.get("kind") or ""),
        account_id=data.get("account_id"),
        last_error=str(data.get("last_error") or ""),
        finished_at=data.get("finished_at"),
    )


def _task_detail_from_row(data: dict[str, Any]) -> AdminTaskDetail:
    raw = data.get("payload")
    payload = raw if isinstance(raw, dict) else {}
    return AdminTaskDetail(
        id=int(data["id"]),
        kind=str(data.get("kind") or ""),
        account_id=data.get("account_id"),
        status=str(data.get("status") or ""),
        payload=sanitize_details(payload),
        attempts=int(data.get("attempts") or 0),
        max_attempts=int(data.get("max_attempts") or 3),
        last_error=str(data.get("last_error") or ""),
        priority=int(data.get("priority") or 100),
        idempotency_key=data.get("idempotency_key"),
        run_at=data.get("run_at"),
        started_at=data.get("started_at"),
        finished_at=data.get("finished_at"),
        created_at=data.get("created_at"),
        updated_at=data.get("updated_at"),
    )


def _task_detail_from_record(task: TaskRecord) -> AdminTaskDetail:
    return _task_detail_from_row(task.model_dump())


def _exec_rowcount(status: object) -> int:
    try:
        return int(str(status).split()[-1])
    except (ValueError, IndexError):
        return 0


def _log_row_from_row(data: dict[str, Any]) -> AdminLogRow:
    raw_fields = data.get("fields")
    fields = raw_fields if isinstance(raw_fields, dict) else {}
    log_id = data.get("id")
    return AdminLogRow(
        id=int(log_id) if log_id is not None else None,
        ts=data.get("ts"),
        level=str(data.get("level") or ""),
        logger=str(data.get("logger") or ""),
        event=str(data.get("event") or ""),
        msg=str(data.get("msg") or ""),
        account_id=data.get("account_id"),
        telegram_username=data.get("telegram_username"),
        telegram_user_id=(
            int(data["telegram_user_id"]) if data.get("telegram_user_id") is not None else None
        ),
        task_id=(str(data["task_id"]) if data.get("task_id") else None),
        fields=fields,
    )


async def _revoke_sessions(account_id: int) -> int:
    """Отозвать сессии без импорта web_auth (platform не тянет домен profile)."""
    try:
        rows = await get_pool().fetch(
            "update account_sessions set revoked_at = now() "
            "where account_id = $1 and revoked_at is null returning id",
            account_id,
        )
    except Exception as exc:
        logger.warning("admin: отзыв сессий account_id=%s не удался: %s", account_id, exc)
        return 0
    return len(rows)


async def _enqueue_admin_message(*, target_account_id: int, text: str) -> None:
    when = datetime.now(UTC)
    minute = when.strftime("%Y%m%d%H%M")
    await enqueue(
        "tg_push",
        payload={
            "kind": "admin_message",
            "vacancy_id": "admin",
            "account_id": target_account_id,
            "text": text,
        },
        priority=40,
        idempotency_key=f"tg_push:admin_message:{target_account_id}:{minute}",
        max_attempts=3,
        account_id=target_account_id,
    )


def _note_query_failure(name: str, exc: Exception, probe: _Probe | None) -> None:
    """Запрос витрины не ответил: в лог — всегда, в сводку — если её собирают прямо сейчас.

    WARNING, а не DEBUG: DEBUG живёт только в файле на ВМ и до `copilot_logs` не доезжает,
    то есть авария витрины не попадала ни в один зип логов.
    """
    if probe is not None:
        probe.failed.append(name)
    event(
        logger,
        "АДМИН",
        "запрос витрины не ответил: %s (%s)",
        name,
        exc,
        level=logging.WARNING,
        query=name,
        error=str(exc),
    )


class _Probe:
    """Копилка провалившихся запросов сводки.

    Раньше сбой любого запроса превращался в пустой список, и панель рисовала «0 аккаунтов,
    0 ошибок, тихо» при лежащем Postgres. Ноль и «не знаю» — разные состояния: собираем имена
    упавших запросов и отдаём их фронту как `degraded`/`degraded_reason`.
    """

    __slots__ = ("failed",)

    def __init__(self) -> None:
        self.failed: list[str] = []

    def note(self, name: str, exc: Exception) -> None:
        _note_query_failure(name, exc, self)

    @property
    def degraded(self) -> bool:
        return bool(self.failed)

    @property
    def reason(self) -> str:
        if not self.failed:
            return ""
        return "не отдали данные: " + ", ".join(self.failed)


async def _fetch(
    sql: str, *args: Any, name: str = "запрос", probe: _Probe | None = None
) -> list[dict[str, Any]]:
    try:
        rows = await get_pool().fetch(sql, *args)
    except Exception as exc:
        _note_query_failure(name, exc, probe)
        return []
    return [row_to_dict(r) for r in rows]


async def _fetchrow(
    sql: str, *args: Any, name: str = "запрос", probe: _Probe | None = None
) -> dict[str, Any] | None:
    try:
        row = await get_pool().fetchrow(sql, *args)
    except Exception as exc:
        _note_query_failure(name, exc, probe)
        return None
    return row_to_dict(row) if row is not None else None


@lru_cache(maxsize=1)
def _extension_version() -> str:
    """Версия из `extension/manifest.json` — тот же канон, что `_extension_manifest_version`."""
    try:
        raw = (_REPO_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
        version = json.loads(raw).get("version")
    except Exception as exc:  # noqa: BLE001 — версия декоративна, не роняет сводку
        logger.debug("admin: не удалось прочитать версию расширения: %s", exc)
        return ""
    return version.strip() if isinstance(version, str) and version.strip() else ""


def _git_sha() -> str:
    """Коммит образа: Dockerfile кладёт ARG GIT_SHA в COPILOT_GIT_SHA."""
    return (os.getenv("COPILOT_GIT_SHA") or os.getenv("GIT_SHA") or "").strip()


def forecast_month_usd(month_usd: float, *, today: date | None = None) -> float:
    """Линейная экстраполяция факта месяца на полный календарный месяц.

    День 25, потрачено $25 → прогноз $31 в августе. Подпись на экране обязана говорить
    «прогноз», иначе число читается как факт.
    """
    day = today or date.today()
    if month_usd <= 0 or day.day <= 0:
        return 0.0
    days_in_month = monthrange(day.year, day.month)[1]
    return round(month_usd / day.day * days_in_month, 4)


def parse_spend_alert_usd(raw: Any) -> float:
    """Порог мягкого лимита: 0 = выключен, мусор и отрицательное — тоже выключен."""
    if isinstance(raw, bool) or raw is None:
        return 0.0
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str) and raw.strip():
        try:
            value = float(raw.strip())
        except ValueError:
            return 0.0
    else:
        return 0.0
    if value != value or value < 0:
        return 0.0
    return round(min(value, SPEND_ALERT_MAX_USD), 2)


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _ms(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return round(number, 1)


def _spend_row_from_row(data: dict[str, Any]) -> AdminSpendRow:
    calls = int(data.get("calls") or 0)
    cache_hits = int(data.get("cache_hits") or 0)
    retries = int(data.get("retries") or 0)
    return AdminSpendRow(
        key=str(data.get("key") or "—"),
        cost_usd=round(float(data.get("cost_usd") or 0.0), 6),
        tokens_in=int(data.get("tokens_in") or 0),
        tokens_out=int(data.get("tokens_out") or 0),
        calls=calls,
        cache_hits=cache_hits,
        cache_hit_rate=_ratio(cache_hits, calls),
        median_ms=_ms(data.get("median_ms")),
        p95_ms=_ms(data.get("p95_ms")),
        retries=retries,
        retry_share=_ratio(retries, calls),
    )


async def _attach_spend_segments(
    rows: list[AdminSpendRow], *, days: int, account_id: int | None
) -> list[AdminSpendRow]:
    """К дневным столбикам — доли моделей. Отдельный запрос: агрегаты дня уже посчитаны."""
    person = "and u.account_id = $2" if account_id is not None else ""
    args: tuple[Any, ...] = (days, account_id) if account_id is not None else (days,)
    # Маркер `u.model` нарочно уникален: тесты пула режут SQL по подстроке, и `generate_series`
    # дневного запроса не должен отдавать эти строки.
    parts = await _fetch(
        "select u.day::date::text as day, "
        "       coalesce(nullif(u.model, ''), 'без модели') as model, "
        "       coalesce(sum(u.cost_usd), 0)::float8 as cost_usd, "
        "       count(u.id)::int as calls "
        "from llm_usage u "
        "where u.day >= current_date - ($1::int - 1) "
        f"{person} "
        "group by 1, 2",
        *args,
        name="расход по моделям дня",
    )
    by_day: dict[str, list[AdminSpendSegment]] = {}
    for part in parts:
        day = str(part.get("day") or "")
        cost = round(float(part.get("cost_usd") or 0.0), 6)
        calls = int(part.get("calls") or 0)
        if not day or (cost <= 0 and calls <= 0):
            continue
        by_day.setdefault(day, []).append(
            AdminSpendSegment(
                key=str(part.get("model") or "без модели"),
                cost_usd=cost,
                calls=calls,
            )
        )
    for bucket in by_day.values():
        bucket.sort(key=lambda item: item.cost_usd, reverse=True)
    return [row.model_copy(update={"segments": by_day.get(row.key, [])}) for row in rows]


async def _load_spend_alert_usd(probe: _Probe | None = None) -> float:
    """Порог из app_settings. Нет строки / сбой чтения → 0 (сигнал выключен, не ложная тревога)."""
    row = await _fetchrow(
        "select value as spend_alert_usd from app_settings where key = $1",
        SPEND_ALERT_KEY,
        name="порог расхода",
        probe=probe,
    )
    return parse_spend_alert_usd((row or {}).get("spend_alert_usd"))


def _queue_from_rows(rows: list[dict[str, Any]]) -> AdminHealthQueue:
    counts = {str(r.get("status") or ""): int(r.get("n") or 0) for r in rows}
    return AdminHealthQueue(
        pending=counts.get("pending", 0),
        running=counts.get("running", 0),
        failed=counts.get("failed", 0),
        done=counts.get("done", 0),
        cancelled=counts.get("cancelled", 0),
    )


async def _load_health(probe: _Probe) -> AdminHealth:
    """Факты здоровья установки. Тон (strong/warn/bad) считает фронт — одна правда."""
    size_row = await _fetchrow(
        "select pg_database_size(current_database())::bigint as size, true as postgres_ok",
        name="размер postgres",
        probe=probe,
    )
    queue_rows = await _fetch(
        "select status, count(*)::int as n from background_tasks group by status",
        name="глубина очереди",
        probe=probe,
    )
    last_row = await _fetchrow(
        "select max(finished_at) as last_finished "
        "from background_tasks where finished_at is not null",
        name="последняя задача",
        probe=probe,
    )
    applied_row = await _fetchrow(
        "select coalesce(max(substring(filename from 1 for 4)::int), 0)::int as applied "
        "from schema_migrations where filename ~ '^[0-9]{4}_'",
        name="применённые миграции",
        probe=probe,
    )
    available = max(migration_numbers() or [0])
    settings = get_settings()
    # postgres_ok — факт успешного запроса размера, а не «весь probe чист»: очередь может
    # упасть отдельно, и тогда degraded=True при живом Postgres.
    postgres_ok = size_row is not None and "размер postgres" not in probe.failed
    try:
        worker_running = bool(get_runtime().running)
    except Exception as exc:  # noqa: BLE001 — воркер не должен ронять сводку
        logger.debug("admin: runtime воркера недоступен: %s", exc)
        worker_running = False
    return AdminHealth(
        extension_version=_extension_version(),
        git_sha=_git_sha(),
        postgres_ok=postgres_ok,
        postgres_size_bytes=(
            int(size_row["size"]) if size_row and size_row.get("size") is not None else None
        ),
        worker_running=worker_running,
        worker_last_finished_at=(last_row or {}).get("last_finished"),
        queue=_queue_from_rows(queue_rows),
        migrations_applied=int((applied_row or {}).get("applied") or 0),
        migrations_available=available,
        model_tier_advanced=settings.model_tier_advanced,
        model_tier_basic=settings.model_tier_basic,
        model_tier_reserve=settings.model_tier_reserve,
    )


async def load_summary() -> AdminSummary:
    """KPI-шапка + здоровье + воронка: лёгкая ручка без выгрузки флота."""
    probe = _Probe()
    accounts_row = await _fetchrow(
        "select count(*) filter (where status = 'active')::int as accounts_active, "
        "count(*) filter (where status = 'active' "
        "  and last_seen_at >= now() - interval '24 hours')::int as seen_24h "
        "from accounts",
        name="аккаунты",
        probe=probe,
    )
    cost_row = await _fetchrow(
        "select coalesce(sum(cost_usd) filter (where day = current_date), 0)::float8 as total, "
        "coalesce(sum(cost_usd) filter ("
        "  where day = current_date and account_id is null"
        "), 0)::float8 as system, "
        "coalesce(sum(cost_usd) filter ("
        "  where day >= current_date - 29"
        "), 0)::float8 as month "
        "from llm_usage",
        name="расход за сегодня и месяц",
        probe=probe,
    )
    errors_row = await _fetchrow(
        "select count(*)::int as total, "
        "count(*) filter (where account_id is null)::int as system "
        "from copilot_logs "
        "where ts >= now() - interval '24 hours' and level in ('ERROR', 'CRITICAL')",
        name="счётчик ошибок",
        probe=probe,
    )
    queues_row = await _fetchrow(
        "select (select count(*)::int from background_tasks where status = 'failed') "
        "         as failed_tasks, "
        "       (select count(*)::int from openrouter_key_requests "
        "         where status in ('pending', 'approved')) as pending_keys",
        name="очереди",
        probe=probe,
    )
    onboarding_row = await _fetchrow(
        "select count(*) filter (where a.status = 'active')::int as telegram, "
        f"count(*) filter (where a.status = 'active' and {_HAS_OPENROUTER_KEY_SQL})::int "
        "  as has_key, "
        f"count(*) filter (where a.status = 'active' and {_HAS_RESUME_SQL})::int "
        "  as has_resume, "
        f"count(*) filter (where a.status = 'active' and {_EXTENSION_CONFIRMED_SQL})::int "
        "  as has_extension "
        "from accounts a",
        name="воронка онбординга",
        probe=probe,
    )
    health = await _load_health(probe)
    spend_alert_usd = await _load_spend_alert_usd(probe)
    accounts = accounts_row or {}
    cost = cost_row or {}
    errors = errors_row or {}
    queues = queues_row or {}
    onboarding = onboarding_row or {}
    return AdminSummary(
        accounts_active=int(accounts.get("accounts_active") or 0),
        seen_24h=int(accounts.get("seen_24h") or 0),
        today_cost_usd=round(float(cost.get("total") or 0.0), 4),
        today_cost_system_usd=round(float(cost.get("system") or 0.0), 4),
        month_cost_usd=round(float(cost.get("month") or 0.0), 4),
        errors_24h=int(errors.get("total") or 0),
        errors_24h_system=int(errors.get("system") or 0),
        pending_keys=int(queues.get("pending_keys") or 0),
        failed_tasks=int(queues.get("failed_tasks") or 0),
        spend_alert_usd=spend_alert_usd,
        health=health,
        onboarding=AdminOnboardingFunnel(
            telegram=int(onboarding.get("telegram") or 0),
            has_key=int(onboarding.get("has_key") or 0),
            has_resume=int(onboarding.get("has_resume") or 0),
            has_extension=int(onboarding.get("has_extension") or 0),
        ),
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


def _resolve_people_order(sort: str) -> str:
    """`sort` → фрагмент `order by` по белому списку.

    Пустой или незнакомый ключ — порядок по умолчанию, а не отказ: сортировка приезжает из URL,
    и устаревшая ссылка должна открывать список, а не ошибку.
    """
    if not sort:
        return _DEFAULT_PEOPLE_ORDER
    column = _PEOPLE_SORT_COLUMNS.get(sort.lstrip("-"))
    if column is None:
        return _DEFAULT_PEOPLE_ORDER
    direction = "desc nulls last" if sort.startswith("-") else "asc nulls last"
    # Вторичный ключ по id — иначе строки с равными значениями скачут между опросами.
    return f"{column} {direction}, p.account_id"


def spend_sparkline_series(
    account_ids: list[int],
    rows: list[dict[str, Any]],
    *,
    days: int = SPEND_SPARKLINE_DAYS,
    today: date | None = None,
) -> dict[int, list[float]]:
    """Собрать 14 точек на человека: дырка в днях — ноль, а не пропуск столбца."""
    day = today or date.today()
    axis = [day - timedelta(days=days - 1 - i) for i in range(days)]
    by_id: dict[int, dict[date, float]] = {aid: {} for aid in account_ids}
    for row in rows:
        aid = int(row["account_id"])
        raw = row.get("day")
        if isinstance(raw, datetime):
            point = raw.date()
        elif isinstance(raw, date):
            point = raw
        else:
            continue
        by_id.setdefault(aid, {})[point] = float(row.get("cost") or 0)
    return {
        aid: [float(by_id.get(aid, {}).get(point, 0.0)) for point in axis] for aid in account_ids
    }


async def _load_people_sparklines(account_ids: list[int], probe: _Probe) -> dict[int, list[float]]:
    empty = {aid: [0.0] * SPEND_SPARKLINE_DAYS for aid in account_ids}
    if not account_ids:
        return empty
    rows = await _fetch(
        "select account_id, day::date as day, coalesce(sum(cost_usd), 0)::float8 as cost "
        "from llm_usage "
        "where account_id = any($1::bigint[]) "
        "  and day >= current_date - ($2::int - 1) "
        "group by account_id, day",
        account_ids,
        SPEND_SPARKLINE_DAYS,
        name="спарклайн расхода",
        probe=probe,
    )
    empty.update(spend_sparkline_series(account_ids, rows))
    return empty


async def load_people(
    *,
    query: str = "",
    status: str = "",
    onboarding: str = "",
    signal: str = "",
    sort: str = "",
    limit: int = 200,
    offset: int = 0,
) -> AdminPeoplePage:
    """Список людей с фильтрами и сортировкой.

    Витрина человека собирается подзапросами (`_USERS_SQL_BODY`), поэтому фильтровать и
    сортировать по её колонкам можно только снаружи: тело заворачивается в подзапрос `p`,
    а `where`/`order by` ссылаются на псевдонимы. `count(*) over ()` даёт полное число
    подходящих — страница отвечает «сколько показано», счётчик «сколько есть».
    Спарклайн 14 дней подгружается вторым запросом по id страницы, не подзапросом на строку.
    """
    if onboarding and onboarding not in _PEOPLE_ONBOARDING_FILTERS:
        raise AdminError(f"Неизвестный фильтр онбординга: {onboarding}")
    if signal and signal not in _PEOPLE_SIGNALS:
        raise AdminError(f"Неизвестный сигнал: {signal}")
    probe = _Probe()
    threshold = await _load_spend_alert_usd(probe)
    conditions = [
        "($1 = '' or p.status = $1)",
        "($2 = '' or p.telegram_username ilike '%' || $2 || '%' "
        "or p.account_id::text like $2 || '%' or p.telegram_user_id::text like $2 || '%' "
        "or p.key_hint ilike '%' || $2 || '%')",
    ]
    args: list[Any] = [
        status if status in _PEOPLE_STATUS_VALUES else "",
        query.strip(),
        limit,
        offset,
    ]
    if onboarding:
        conditions.append(_PEOPLE_ONBOARDING_FILTERS[onboarding])
    if signal in _PEOPLE_SIGNAL_FILTERS:
        conditions.append(_PEOPLE_SIGNAL_FILTERS[signal])
    elif signal == "spend":
        # Порог 0 = сигнал выключен: фильтр не должен показывать весь флот.
        if threshold <= 0:
            conditions.append("false")
        else:
            args.append(threshold)
            conditions.append(f"p.spend_month_usd > ${len(args)}")
    sql = (
        f"select p.*, count(*) over ()::int as total_count "
        f"from ({_USERS_SQL_BODY}) p "
        f"where {' and '.join(conditions)} "
        f"order by {_resolve_people_order(sort)} limit $3 offset $4"
    )
    rows = await _fetch(
        sql,
        *args,
        name="люди",
        probe=probe,
    )
    items = [_user_from_row(r) for r in rows]
    ids = [user.account_id for user in items]
    series = await _load_people_sparklines(ids, probe)
    pipeline = await _load_people_pipeline(ids, probe)
    items = [
        user.model_copy(
            update={
                "spend_14d": series.get(user.account_id, []),
                "spend_alert": threshold > 0 and user.spend_month_usd > threshold,
                "pipeline": pipeline.get(user.account_id),
            }
        )
        for user in items
    ]
    return AdminPeoplePage(
        items=items,
        total=int(rows[0].get("total_count") or 0) if rows else 0,
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def load_attention() -> AdminAttention:
    """Очередь внимания (Этап 1.1): заявки, сбои, свежие ошибки, «отвалившиеся».

    Здесь только сбор. Порядок карточек и подписи — на фронте (`attention.ts`), чтобы правило
    «что срочнее» проверялось без БД.
    """
    probe = _Probe()
    key_rows = await _fetch(
        "select r.id, r.account_id, a.telegram_username, r.status, r.requested_at, r.note "
        "from openrouter_key_requests r join accounts a on a.id = r.account_id "
        "where r.status in ('pending', 'approved') order by r.requested_at",
        name="заявки на ключ",
        probe=probe,
    )
    task_rows = await _fetch(
        "select id, kind, account_id, last_error, finished_at from background_tasks "
        "where status = 'failed' order by finished_at desc nulls last limit 20",
        name="упавшие задачи",
        probe=probe,
    )
    error_rows = await _fetch(
        "select l.ts, l.level, l.event, l.msg, l.account_id, a.telegram_username "
        "from copilot_logs l left join accounts a on a.id = l.account_id "
        "where l.ts >= now() - interval '24 hours' and l.level in ('ERROR', 'CRITICAL') "
        "order by l.ts desc limit 20",
        name="ошибки",
        probe=probe,
    )
    totals_row = await _fetchrow(
        "select (select count(*)::int from background_tasks where status = 'failed') as tasks, "
        "       (select count(*)::int from copilot_logs "
        "         where ts >= now() - interval '24 hours' "
        "           and level in ('ERROR', 'CRITICAL')) as errors",
        name="счётчики очереди",
        probe=probe,
    )
    # «Отвалившийся» — тот, кто дошёл до резюме и пропал. Без резюме молчание ничего не значит:
    # человек просто не начал, и это забота онбординга, а не очереди внимания.
    stale_rows = await _fetch(
        "select a.id as account_id, a.telegram_username, "
        "  case when a.last_seen_at is null then null "
        "       else extract(day from now() - a.last_seen_at)::int end as days_silent "
        "from accounts a "
        "where a.status = 'active' and a.role = 'member' "
        "  and (a.last_seen_at is null or a.last_seen_at < now() - interval '7 days') "
        f"  and {_HAS_RESUME_SQL} "
        "order by a.last_seen_at asc nulls first limit 10",
        name="отвалившиеся",
        probe=probe,
    )
    burst_rows = await _fetch(
        "select l.account_id, a.telegram_username, count(*)::int as n "
        "from copilot_logs l join accounts a on a.id = l.account_id "
        "where l.ts >= now() - interval '1 hour' "
        "  and l.level in ('ERROR', 'CRITICAL') "
        "group by l.account_id, a.telegram_username "
        "order by n desc limit 10",
        name="пачки ошибок",
        probe=probe,
    )
    # Без ключа третий день и без открытой заявки: заявки уже висят отдельными карточками,
    # дублировать человека в очереди внимания нельзя.
    no_key_rows = await _fetch(
        "select a.id as account_id, a.telegram_username, "
        "  extract(day from now() - a.created_at)::int as days_waiting "
        "from accounts a "
        "where a.status = 'active' and a.role = 'member' "
        "  and a.created_at < now() - interval '2 days' "
        f"  and not {_HAS_OPENROUTER_KEY_SQL} "
        "  and not exists ("
        "    select 1 from openrouter_key_requests r "
        "    where r.account_id = a.id and r.status in ('pending', 'approved')"
        "  ) "
        "order by a.created_at asc limit 10",
        name="ждут ключ без заявки",
        probe=probe,
    )
    totals = totals_row or {}
    threshold = await _load_spend_alert_usd(probe)
    spend_over_rows: list[dict[str, Any]] = []
    if threshold > 0:
        spend_over_rows = await _fetch(
            "select a.id as account_id, a.telegram_username, "
            "coalesce(sum(u.cost_usd), 0)::float8 as month_usd "
            "from accounts a join llm_usage u on u.account_id = a.id "
            "  and u.day >= date_trunc('month', current_date)::date "
            "where a.status = 'active' "
            "group by a.id, a.telegram_username "
            "having coalesce(sum(u.cost_usd), 0) > $1 "
            "order by month_usd desc limit 10",
            threshold,
            name="превысили порог",
            probe=probe,
        )
    return AdminAttention(
        key_requests=[_key_request_from_row(r) for r in key_rows],
        failed_tasks=[_task_from_row(r) for r in task_rows],
        failed_tasks_total=int(totals.get("tasks") or 0),
        errors=[_log_row_from_row(r) for r in error_rows],
        errors_total=int(totals.get("errors") or 0),
        error_bursts=[
            AdminErrorBurst(
                account_id=int(r["account_id"]),
                telegram_username=r.get("telegram_username"),
                count=int(r.get("n") or 0),
            )
            for r in burst_rows
        ],
        stale=[
            AdminStaleAccount(
                account_id=int(r["account_id"]),
                telegram_username=r.get("telegram_username"),
                days_silent=int(r["days_silent"]) if r.get("days_silent") is not None else None,
            )
            for r in stale_rows
        ],
        no_key=[
            AdminNoKeyWait(
                account_id=int(r["account_id"]),
                telegram_username=r.get("telegram_username"),
                days_waiting=int(r.get("days_waiting") or 0),
            )
            for r in no_key_rows
        ],
        spend_over=[
            AdminSpendOver(
                account_id=int(r["account_id"]),
                telegram_username=r.get("telegram_username"),
                month_usd=round(float(r.get("month_usd") or 0.0), 4),
            )
            for r in spend_over_rows
        ],
        spend_alert_usd=threshold,
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def load_spend(
    *, days: int = 14, group_by: str = "day", account_id: int | None = None
) -> AdminSpend:
    """Разрез расхода по дням/моделям/фичам/людям.

    `today_usd` считается тем же условием, что KPI `/summary` (`day = current_date`,
    вся таблица) — иначе столбик «сегодня» не сойдётся с числом над графиком.
    `account_id` сужает ту же витрину до одного человека (вкладка «Расход» в карточке).
    """
    group = _SPEND_GROUPS.get(group_by)
    if group is None:
        raise AdminError(f"Неизвестный разрез расхода: {group_by}")
    key_expr, order = group
    probe = _Probe()
    person = "and u.account_id = $2" if account_id is not None else ""
    args: tuple[Any, ...] = (days, account_id) if account_id is not None else (days,)
    if group_by == "day":
        rows = await _fetch(
            # `generate_series(..., interval '1 day')` даёт timestamptz — без `::date`
            # ключом становится «2026-08-12 00:00:00+00», и подпись оси графика (а заодно
            # колонка «Разрез») печатает сырой таймстемп вместо «12.08».
            "select g.day::date::text as key, "
            f"{_SPEND_ROW_AGG}"
            "from generate_series("
            "  current_date - ($1::int - 1), current_date, interval '1 day'"
            ") as g(day) "
            f"left join llm_usage u on u.day = g.day::date {person} "
            "group by 1 order by 1 desc",
            *args,
            name="расход",
            probe=probe,
        )
    else:
        rows = await _fetch(
            f"select {key_expr} as key, "
            f"{_SPEND_ROW_AGG}"
            "from llm_usage u left join accounts a on a.id = u.account_id "
            "where u.day >= current_date - ($1::int - 1) "
            f"{person} "
            f"group by 1 order by {order}",
            *args,
            name="расход",
            probe=probe,
        )
    person_totals = "and account_id = $2" if account_id is not None else ""
    totals_row = await _fetchrow(
        "select coalesce(sum(cost_usd) filter (where day = current_date), 0)::float8 "
        "         as today_usd, "
        "       coalesce(sum(cost_usd) filter ("
        "         where day >= date_trunc('month', current_date)::date"
        "       ), 0)::float8 as month_usd, "
        "       count(*) filter ("
        "         where cache_hit and day >= current_date - ($1::int - 1)"
        "       )::int as cache_hits, "
        "       count(*) filter ("
        "         where day >= current_date - ($1::int - 1)"
        "       )::int as cache_calls, "
        "       percentile_cont(0.5) within group (order by total_ms) filter ("
        "         where total_ms is not null and day >= current_date - ($1::int - 1)"
        "       ) as median_ms, "
        "       percentile_cont(0.95) within group (order by total_ms) filter ("
        "         where total_ms is not null and day >= current_date - ($1::int - 1)"
        "       ) as p95_ms, "
        "       count(*) filter ("
        "         where coalesce(attempt, 1) > 1 and day >= current_date - ($1::int - 1)"
        "       )::int as retries "
        f"from llm_usage where true {person_totals}",
        *args,
        name="итоги расхода",
        probe=probe,
    )
    spend_rows = [_spend_row_from_row(r) for r in rows]
    if group_by == "day":
        spend_rows = await _attach_spend_segments(spend_rows, days=days, account_id=account_id)
    totals = totals_row or {}
    cache_calls = int(totals.get("cache_calls") or 0)
    cache_hits = int(totals.get("cache_hits") or 0)
    retries = int(totals.get("retries") or 0)
    month_usd = round(float(totals.get("month_usd") or 0.0), 4)
    return AdminSpend(
        group_by=group_by,
        days=days,
        rows=spend_rows,
        total_usd=round(sum(r.cost_usd for r in spend_rows), 4),
        today_usd=round(float(totals.get("today_usd") or 0.0), 4),
        month_usd=month_usd,
        forecast_month_usd=forecast_month_usd(month_usd),
        cache_hits=cache_hits,
        cache_calls=cache_calls,
        cache_hit_rate=_ratio(cache_hits, cache_calls),
        median_ms=_ms(totals.get("median_ms")),
        p95_ms=_ms(totals.get("p95_ms")),
        retries=retries,
        retry_share=_ratio(retries, cache_calls),
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def load_user_detail(account_id: int) -> AdminUserDetail:
    row = await _fetchrow(_USER_BY_ID_SQL, account_id, name="карточка человека")
    if row is None:
        raise AdminError("Аккаунт не найден", status=404)
    funnel_rows = await _fetch(
        "select coalesce(status, '') as status, count(*)::int as n "
        "from jobs where account_id = $1 group by status",
        account_id,
        name="воронка человека",
    )
    err_rows = await _fetch(
        "select ts, level, event, msg, account_id from copilot_logs "
        "where account_id = $1 and ts >= now() - interval '7 days' "
        "and level in ('ERROR', 'CRITICAL') order by ts desc limit 10",
        account_id,
        name="ошибки человека",
    )
    action_rows = await _fetch(
        "select at, kind, label from ("
        "  (select ts as at, 'nav'::text as kind, "
        "          case when msg like 'Экран %%' then substr(msg, 7) else msg end as label "
        "   from copilot_logs "
        "   where account_id = $1 and logger = 'frontend' "
        "     and fields->>'kind' = 'nav' "
        "     and (msg like 'Экран %%' or msg like 'Клик %%') "
        "   order by ts desc limit 12)"
        "  union all "
        "  (select ts as at, 'feature'::text as kind, agent as label "
        "   from llm_usage where account_id = $1 "
        "   order by ts desc limit 12)"
        ") actions order by at desc nulls last limit 6",
        account_id,
        name="действия человека",
    )
    # Расход теперь приезжает той же строкой, что и остальная витрина человека (_USERS_SQL),
    # отдельный запрос по llm_usage не нужен — дублировал те же суммы.
    user = _user_from_row(row)
    return AdminUserDetail(
        user=user,
        funnel=FunnelCounts(counts={str(r["status"] or "—"): int(r["n"]) for r in funnel_rows}),
        today_cost_usd=user.today_cost_usd,
        month_cost_usd=user.month_cost_usd,
        month_tokens_in=user.month_tokens_in,
        month_tokens_out=user.month_tokens_out,
        recent_errors=[
            AdminLogRow(
                ts=r.get("ts"),
                level=str(r.get("level") or ""),
                event=str(r.get("event") or ""),
                msg=str(r.get("msg") or ""),
                account_id=account_id,
            )
            for r in err_rows
        ],
        recent_actions=[
            AdminRecentAction(
                at=r.get("at"),
                kind=str(r.get("kind") or ""),
                label=str(r.get("label") or ""),
            )
            for r in action_rows
        ],
        sessions=int(row.get("session_count") or 0),
        session_list=await _load_user_sessions(account_id),
        snapshot=await _load_account_snapshot(account_id, probe=_Probe()),
        telegram_outbox=await _load_telegram_outbox(account_id),
    )


async def _load_account_snapshot(account_id: int, *, probe: _Probe) -> AdminAccountSnapshot:
    resume_row = await _fetchrow(
        "select updated_at, octet_length(data::text)::int as bytes, data "
        "from resumes where account_id = $1",
        account_id,
        name="резюме человека",
        probe=probe,
    )
    title, grades, formats = search_profile_lines((resume_row or {}).get("data"))
    ext_row = await _fetchrow(
        "select fields->>'config_version' as version, ts "
        "from copilot_logs "
        "where account_id = $1 and event = 'РАСШИРЕНИЕ' "
        "  and fields->>'kind' = 'extension_parse' "
        "  and coalesce(fields->>'config_version', '') <> '' "
        "order by ts desc limit 1",
        account_id,
        name="версия расширения",
        probe=probe,
    )
    scored_row = await _fetchrow(
        "select max(scored_at) as last_scored from jobs where account_id = $1",
        account_id,
        name="последний скоринг",
        probe=probe,
    )
    devices_row = await _fetchrow(
        "select count(*) filter (where revoked_at is null)::int as sessions, "
        "count(distinct login_user_agent) filter ("
        "  where revoked_at is null and login_user_agent is not null"
        ")::int as devices "
        "from account_sessions where account_id = $1",
        account_id,
        name="устройства",
        probe=probe,
    )
    settings_rows = await _fetch(
        "select key, value from account_settings where account_id = $1 and key = any($2::text[])",
        account_id,
        [
            "salary_min_override",
            "auto_apply_config",
            "discovery_config",
            "auto_apply_runner_tick",
            "discovery_runner_tick",
        ],
        name="настройки человека",
        probe=probe,
    )
    settings = {str(r.get("key") or ""): r.get("value") for r in settings_rows}
    return AdminAccountSnapshot(
        resume_updated_at=(resume_row or {}).get("updated_at"),
        resume_bytes=(resume_row or {}).get("bytes"),
        search_title=title,
        search_grades=grades,
        search_formats=formats,
        extension_version=str((ext_row or {}).get("version") or ""),
        last_extension_at=(ext_row or {}).get("ts"),
        last_scored_at=(scored_row or {}).get("last_scored"),
        device_count=int((devices_row or {}).get("devices") or 0),
        salary_min_override=_salary_override(settings.get("salary_min_override")),
        auto_apply=_any_platform_enabled(settings.get("auto_apply_config")),
        discovery=_any_platform_enabled(settings.get("discovery_config")),
        auto_apply_last_tick_at=_runner_tick_at(settings.get("auto_apply_runner_tick")),
        discovery_last_tick_at=_runner_tick_at(settings.get("discovery_runner_tick")),
    )


async def _load_telegram_outbox(account_id: int) -> list[AdminTelegramSent]:
    rows = await _fetch(
        "select ts, coalesce(fields->>'text_preview', msg) as preview "
        "from copilot_logs "
        "where event = 'АДМИН' and fields->>'action' = 'telegram' "
        "  and (fields->>'target_account_id')::bigint = $1 "
        "order by ts desc limit 10",
        account_id,
        name="исходящие телеграм",
    )
    return [
        AdminTelegramSent(ts=r.get("ts"), preview=str(r.get("preview") or "").strip()) for r in rows
    ]


async def _load_user_sessions(account_id: int) -> list[AdminDeviceSession]:
    rows = await _fetch(
        "select id, issued_at, login_ip, login_user_agent "
        "from account_sessions "
        "where account_id = $1 and revoked_at is null "
        "order by issued_at desc",
        account_id,
        name="сессии человека",
    )
    return [
        AdminDeviceSession(
            id=int(r["id"]),
            issued_at=r.get("issued_at"),
            login_ip=(str(r["login_ip"]).strip() or None) if r.get("login_ip") else None,
            login_user_agent=(str(r["login_user_agent"]).strip() or None)
            if r.get("login_user_agent")
            else None,
        )
        for r in rows
    ]


async def revoke_one_user_session(target_id: int, session_id: int, *, actor_id: int) -> bool:
    """Отозвать одну сессию человека. SQL здесь, без импорта web_auth (домен profile)."""
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    try:
        row = await get_pool().fetchrow(
            "update account_sessions set revoked_at = now() "
            "where id = $1 and account_id = $2 and revoked_at is null returning id",
            session_id,
            target_id,
        )
    except Exception as exc:
        logger.warning(
            "admin: отзыв сессии session_id=%s account_id=%s не удался: %s",
            session_id,
            target_id,
            exc,
        )
        raise AdminError("Не удалось отозвать сессию", status=503) from exc
    if row is None:
        raise AdminError("Сессия не найдена", status=404)
    await _log_action(
        "revoke_session", actor_id, target_account_id=target_id, session_id=session_id
    )
    return True


_SUPPORT_CHANNELS = frozenset({"user", "agent"})
_SUPPORT_BODY_MAX = 3500
_SUPPORT_HISTORY = 80


def _clip_support_body(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= _SUPPORT_BODY_MAX:
        return cleaned
    return cleaned[:_SUPPORT_BODY_MAX].rstrip()


async def _insert_support_message(
    *,
    account_id: int,
    channel: str,
    role: str,
    body: str,
    reply_to_id: int | None = None,
) -> AdminSupportMessage:
    row = await get_pool().fetchrow(
        "insert into admin_support_messages "
        "(account_id, channel, role, body, reply_to_id) "
        "values ($1, $2, $3, $4, $5) "
        "returning id, account_id, channel, role, body, reply_to_id, created_at",
        account_id,
        channel,
        role,
        body,
        reply_to_id,
    )
    if row is None:
        raise AdminError("Не удалось сохранить сообщение", status=503)
    data = row_to_dict(row)
    return AdminSupportMessage(
        id=int(data["id"]),
        channel=str(data["channel"]),
        role=str(data["role"]),
        body=str(data["body"] or ""),
        reply_to_id=data.get("reply_to_id"),
        created_at=data.get("created_at"),
    )


async def load_support_thread(account_id: int) -> AdminSupportThread:
    target = await get_account_by_id(account_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    probe = _Probe()
    rows = await _fetch(
        "select id, channel, role, body, reply_to_id, created_at "
        "from admin_support_messages "
        "where account_id = $1 order by created_at asc, id asc "
        f"limit {_SUPPORT_HISTORY}",
        account_id,
        name="лента поддержки",
        probe=probe,
    )
    return AdminSupportThread(
        items=[
            AdminSupportMessage(
                id=int(r["id"]),
                channel=str(r.get("channel") or "user"),
                role=str(r.get("role") or "admin"),
                body=str(r.get("body") or ""),
                reply_to_id=r.get("reply_to_id"),
                created_at=r.get("created_at"),
            )
            for r in rows
        ],
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def record_inbound_user_telegram(account_id: int, text: str) -> None:
    """Входящее из бота — в канал user. Сбой записи не должен ронять обработку апдейта."""
    cleaned = _clip_support_body(text)
    if not cleaned:
        return
    try:
        await _insert_support_message(
            account_id=account_id, channel="user", role="user", body=cleaned
        )
    except Exception as exc:
        logger.debug("admin: входящее в ленту поддержки не записалось: %s", exc)


async def send_support_message(
    target_id: int,
    *,
    channel: str,
    text: str,
    actor_id: int,
    reply_to_id: int | None = None,
) -> AdminSupportThread:
    """Реплика оператора: в канал user уходит в Telegram, в канал agent — к LLM."""
    cleaned = _clip_support_body(text)
    if not cleaned:
        raise AdminError("Пустое сообщение")
    if channel not in _SUPPORT_CHANNELS:
        raise AdminError("Канал может быть только user или agent")
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    if channel == "user":
        await enqueue_admin_telegram(target_id, cleaned, actor_id=actor_id, persist=False)
        await _insert_support_message(
            account_id=target_id,
            channel="user",
            role="admin",
            body=cleaned,
            reply_to_id=reply_to_id,
        )
        return await load_support_thread(target_id)
    await _insert_support_message(
        account_id=target_id,
        channel="agent",
        role="admin",
        body=cleaned,
        reply_to_id=reply_to_id,
    )
    await _reply_support_agent(target_id)
    await _log_action("support_agent", actor_id, target_account_id=target_id)
    return await load_support_thread(target_id)


def _support_agent_tail(detail: AdminUserDetail, thread: AdminSupportThread) -> str:
    user = detail.user
    origin = (
        "выдан вами"
        if user.key_origin == "admin"
        else "свой"
        if user.key_origin == "self"
        else "нет"
    )
    telegram = "привязан" if user.telegram_chat_id else "нет чата"
    lines = [
        f"Человек: @{user.telegram_username or '—'} (id {user.account_id})",
        f"Статус: {user.status} · роль {user.role} · telegram {telegram}",
        f"Ключ OpenRouter: {origin}" + (f" {user.key_hint}" if user.key_hint else ""),
        f"Резюме: {'есть' if user.has_resume else 'нет'} · "
        f"расширение: {'есть' if user.extension_confirmed else 'нет'}",
        f"Ошибки за сутки: {user.errors_24h} · сегодня ${user.today_cost_usd:.2f}",
    ]
    errors = [row.msg or row.event for row in detail.recent_errors[:5] if row.msg or row.event]
    if errors:
        lines.append("Свежие ошибки: " + " · ".join(errors))
    title = detail.snapshot.search_title
    if title:
        lines.append(f"Поиск: {title}")
    history: list[str] = []
    for item in thread.items[-20:]:
        who = {"admin": "оператор", "user": "человек", "agent": "агент"}.get(item.role, item.role)
        history.append(f"{who} [{item.channel}]: {item.body[:400]}")
    if history:
        lines.append("Лента:\n" + "\n".join(history))
    return "\n".join(lines)


async def _reply_support_agent(account_id: int) -> None:
    from core.platform.llm.call import CallContext, run

    detail = await load_user_detail(account_id)
    thread = await load_support_thread(account_id)
    last = next((item.body for item in reversed(thread.items) if item.role == "admin"), "")
    try:
        answer = await run(
            "admin_support",
            user=last or "Что проверить у этого человека?",
            dynamic_tail=_support_agent_tail(detail, thread),
            ctx=CallContext(skip_cache=True, skip_single_flight=True),
        )
    except Exception as exc:
        event(
            logger,
            "АДМИН",
            "агент поддержки не ответил: %s",
            exc,
            level=logging.WARNING,
            account_id=account_id,
        )
        answer = "Не смог ответить. Посмотрите диагноз и журнал — там обычно уже есть зацепка."
    text = _clip_support_body(str(answer or "").strip())
    if not text:
        text = "Пустой ответ агента. Спросите иначе или откройте журнал."
    await _insert_support_message(account_id=account_id, channel="agent", role="agent", body=text)


async def load_user_diagnosis(account_id: int) -> AdminDiagnosis:
    """Вердикт «что не так»: факты карточки + проба ключа. Сырой ключ в ответ не попадает."""
    detail = await load_user_detail(account_id)
    key_alive: bool | None = None
    key_network_error = False
    if detail.user.has_openrouter_key:
        raw = await _load_raw_openrouter_key(account_id)
        if raw:
            probe = await openrouter_keys.verify_key(raw)
            key_alive = probe.alive
            key_network_error = probe.network_error
        else:
            key_alive = False
    items = facts_from_user(
        detail.user,
        detail.snapshot,
        key_alive=key_alive,
        key_network_error=key_network_error,
        current_extension_version=_extension_version(),
    )
    return AdminDiagnosis(items=items)


async def _load_raw_openrouter_key(account_id: int) -> str:
    row = await _fetchrow(
        "select value #>> '{}' as raw_key from account_settings "
        "where account_id = $1 and key = 'openrouter_api_key'",
        account_id,
        name="ключ для пробы",
    )
    return str((row or {}).get("raw_key") or "").strip()


def parse_log_levels(raw: str) -> list[str]:
    """Мультивыбор `ERROR,WARNING`. Пустое и мусор — уровни по умолчанию, не отказ."""
    parts = [item.strip().upper() for item in (raw or "").split(",") if item.strip()]
    levels = [item for item in parts if item in LOG_LEVELS]
    if not levels:
        return list(DEFAULT_LOG_LEVELS)
    if "ERROR" in levels and "CRITICAL" not in levels:
        levels.append("CRITICAL")
    return levels


def resolve_log_window(
    since: datetime | None,
    until: datetime | None,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Окно журнала: по умолчанию последний час, потолок — 14 дней."""
    moment = now or datetime.now(UTC)

    def _aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    end = _aware(until) or moment
    start = _aware(since) or (end - DEFAULT_LOG_WINDOW)
    if start >= end:
        raise AdminError("Начало окна журнала должно быть раньше конца")
    if end - start > MAX_LOG_WINDOW:
        raise AdminError("Окно журнала не больше 14 дней")
    return start, end


def compile_log_query(
    *,
    since: datetime,
    until: datetime,
    levels: list[str],
    account_id: int | None = None,
    telegram_user_id: int | None = None,
    logger_name: str = "",
    event_name: str = "",
    query: str = "",
    cursor: tuple[datetime, int] | None = None,
    limit: int = DEFAULT_LOG_LIMIT,
) -> tuple[str, list[Any]]:
    """SQL журнала + параметры. Имена фильтров в текст не подставляются."""
    conditions = ["l.ts >= $1", "l.ts < $2", "l.level = any($3::text[])"]
    args: list[Any] = [since, until, levels]
    if account_id is not None:
        args.append(account_id)
        conditions.append(f"l.account_id = ${len(args)}")
    if telegram_user_id is not None:
        args.append(telegram_user_id)
        conditions.append(f"a.telegram_user_id = ${len(args)}")
    logger_name = logger_name.strip()
    if logger_name:
        args.append(logger_name)
        conditions.append(f"l.logger ilike '%' || ${len(args)} || '%'")
    event_name = event_name.strip()
    if event_name:
        args.append(event_name)
        conditions.append(f"l.event = ${len(args)}")
    query = query.strip()
    if query:
        args.append(query)
        conditions.append(f"l.msg ilike '%' || ${len(args)} || '%'")
    if cursor is not None:
        cursor_ts, cursor_id = cursor
        args.extend([cursor_ts, cursor_id])
        conditions.append(f"(l.ts, l.id) < (${len(args) - 1}, ${len(args)})")
    args.append(limit + 1)
    sql = (
        "select l.id, l.ts, l.level, l.logger, l.event, l.task_id, l.msg, "
        "l.account_id, a.telegram_username, a.telegram_user_id, l.fields "
        "from copilot_logs l left join accounts a on a.id = l.account_id "
        f"where {' and '.join(conditions)} "
        f"order by l.ts desc, l.id desc limit ${len(args)}"
    )
    return sql, args


async def _fetch_logs(sql: str, args: list[Any]) -> list[dict[str, Any]]:
    """Выборка журнала с `statement_timeout`: без него широкий фильтр держит пул."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL statement_timeout = '{LOG_STATEMENT_TIMEOUT}'")
            rows = await conn.fetch(sql, *args)
    except Exception as exc:
        name = type(exc).__name__
        if name == "QueryCanceledError":
            raise AdminError(
                "Запрос журнала превысил лимит времени — сузьте окно или фильтры"
            ) from exc
        event(
            logger,
            "АДМИН",
            "запрос журнала не ответил: %s",
            exc,
            level=logging.WARNING,
            query="журнал",
            error=str(exc),
        )
        raise AdminError("Не удалось прочитать журнал", status=503) from exc
    return [row_to_dict(r) for r in rows]


async def load_logs(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    level: str = "",
    account_id: int | None = None,
    telegram_user_id: int | None = None,
    logger_name: str = "",
    event_name: str = "",
    query: str = "",
    cursor: str = "",
    limit: int = DEFAULT_LOG_LIMIT,
) -> AdminLogPage:
    """Журнал copilot_logs — то, ради чего сейчас ходят по ssh (Этап 5.1)."""
    if query.strip() and len(query.strip()) < MIN_LOG_QUERY_LEN:
        raise AdminError("Поиск по тексту — от трёх символов")
    capped = min(max(limit, 1), MAX_LOG_LIMIT)
    start, end = resolve_log_window(since, until)
    parsed_cursor = decode_cursor(cursor) if cursor.strip() else None
    sql, args = compile_log_query(
        since=start,
        until=end,
        levels=parse_log_levels(level),
        account_id=account_id,
        telegram_user_id=telegram_user_id,
        logger_name=logger_name,
        event_name=event_name,
        query=query,
        cursor=parsed_cursor,
        limit=capped,
    )
    rows = await _fetch_logs(sql, args)
    page = rows[:capped]
    next_cursor = None
    if len(rows) > capped and page:
        last = page[-1]
        ts = last.get("ts")
        log_id = last.get("id")
        if isinstance(ts, datetime) and log_id is not None:
            next_cursor = encode_cursor(ts, int(log_id))
    return AdminLogPage(
        items=[_log_row_from_row(r) for r in page],
        next_cursor=next_cursor,
        since=start,
        until=end,
    )


async def load_audit_page(
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    account_id: int | None = None,
    telegram_user_id: int | None = None,
    cursor: str = "",
    limit: int = DEFAULT_LOG_LIMIT,
) -> AdminAuditPage:
    """Вкладка «Аудит»: кто, что, кому, когда. То же окно и курсор, что у журнала."""
    capped = min(max(limit, 1), MAX_LOG_LIMIT)
    start, end = resolve_log_window(since, until)
    parsed_cursor = decode_cursor(cursor) if cursor.strip() else None
    return await load_audit(
        since=start,
        until=end,
        target_id=account_id,
        telegram_user_id=telegram_user_id,
        cursor=parsed_cursor,
        limit=capped,
    )


async def disable_user(target_id: int, *, actor_id: int, reason: str = "") -> None:
    if target_id == actor_id:
        raise AdminError("Нельзя отключить свой аккаунт")
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    if target.role == "owner":
        raise AdminError("Нельзя отключить оператора установки")
    await disable_account(target_id, reason=reason)
    await _revoke_sessions(target_id)
    await _log_action(
        "disable", actor_id, target_account_id=target_id, reason=(reason or "").strip()
    )


async def enable_user(target_id: int, *, actor_id: int) -> None:
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    await enable_account(target_id)
    await _log_action("enable", actor_id, target_account_id=target_id)


async def revoke_user_sessions(target_id: int, *, actor_id: int) -> int:
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    revoked = await _revoke_sessions(target_id)
    await _log_action("revoke_sessions", actor_id, target_account_id=target_id, revoked=revoked)
    return revoked


async def user_log_bundle(target_id: int, *, actor_id: int, hours: int) -> bytes:
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    await _log_action("log_bundle", actor_id, target_account_id=target_id, hours=hours)
    return await build_log_bundle_zip(target_id, window_hours=hours)


async def reject_key_request(request_id: int, *, actor_id: int) -> None:
    """Отклонить заявку на ключ; заявитель получает вежливое уведомление в Telegram."""
    try:
        target_account_id = await openrouter_keys.reject_request(
            request_id=request_id, actor_id=actor_id
        )
    except OpenRouterKeyError as exc:
        raise AdminError(str(exc)) from exc
    await openrouter_keys.notify_key_rejected(target_account_id=target_account_id)
    await _log_action(
        "key_reject", actor_id, target_account_id=target_account_id, request_id=request_id
    )


async def issue_user_key(
    target_id: int, raw_key: str, *, actor_id: int, label: str | None = None
) -> None:
    """Выдать или перевыпустить ключ человеку. Открытая заявка закрывается сама.

    Пользователю уходит уведомление о факте выдачи — но НЕ сам ключ: операторский ключ он не
    видит нигде (ни в вебе, ни в боте), иначе «выдал» ничем не отличается от «отдал».
    """
    try:
        await openrouter_keys.issue_key(
            target_account_id=target_id, raw_key=raw_key, actor_id=actor_id, label=label
        )
    except OpenRouterKeyError as exc:
        raise AdminError(str(exc)) from exc
    await openrouter_keys.notify_key_issued(target_account_id=target_id)
    await _log_action(
        "key_issue", actor_id, target_account_id=target_id, key_hint=mask_key(raw_key)
    )


async def revoke_user_key(target_id: int, *, actor_id: int) -> None:
    """Убрать ключ у человека (в кабинете OpenRouter он гасится отдельно)."""
    try:
        await openrouter_keys.revoke_key(target_account_id=target_id, actor_id=actor_id)
    except OpenRouterKeyError as exc:
        raise AdminError(str(exc)) from exc
    await _log_action("key_revoke", actor_id, target_account_id=target_id)


async def enqueue_admin_telegram(
    target_id: int, text: str, *, actor_id: int, persist: bool = True
) -> None:
    cleaned = text.strip()
    if not cleaned:
        raise AdminError("Пустое сообщение")
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    if target.status != "active" or target.telegram_chat_id is None:
        raise AdminError("У человека нет привязанного Telegram")
    await _enqueue_admin_message(target_account_id=target_id, text=cleaned)
    if persist:
        try:
            await _insert_support_message(
                account_id=target_id, channel="user", role="admin", body=_clip_support_body(cleaned)
            )
        except Exception as exc:
            logger.debug("admin: исходящее в ленту поддержки не записалось: %s", exc)
    await _log_action("telegram", actor_id, target_account_id=target_id, text_preview=cleaned[:200])


async def set_user_role(target_id: int, role: str, *, actor_id: int) -> None:
    if role not in {"owner", "member"}:
        raise AdminError("Роль может быть только owner или member")
    new_role: Role = "owner" if role == "owner" else "member"
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    if target.role == new_role:
        return
    if target.role == "owner" and new_role == "member":
        owners = [a for a in await list_active_accounts() if a.role == "owner"]
        if len(owners) <= 1:
            raise AdminError("Нельзя снять роль с последнего оператора")
    await set_account_role(target_id, new_role)
    await _log_action("role_change", actor_id, target_account_id=target_id, role=new_role)


async def set_user_note(target_id: int, note: str, *, actor_id: int) -> None:
    target = await get_account_by_id(target_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    await set_account_note(target_id, note)
    await _log_action("note", actor_id, target_account_id=target_id)


async def verify_user_key(raw_key: str) -> AdminKeyVerify:
    """Проверить ключ у OpenRouter до выдачи. Сеть не роняет ручку."""
    return _key_verify_from_probe(await openrouter_keys.verify_key(raw_key))


async def verify_stored_user_key(account_id: int) -> AdminKeyVerify:
    """Проверить уже привязанный ключ, не показывая секрет."""
    target = await get_account_by_id(account_id)
    if target is None:
        raise AdminError("Аккаунт не найден", status=404)
    raw = await _load_raw_openrouter_key(account_id)
    if not raw:
        raise AdminError("У человека нет ключа")
    return _key_verify_from_probe(await openrouter_keys.verify_key(raw))


async def refresh_key_balances() -> AdminKeyBalances:
    """Остатки по ключам origin=admin. Кнопка, не опрос: это чужой внешний сервис."""
    rows = await openrouter_keys.refresh_admin_issued_balances()
    return AdminKeyBalances(
        items=[
            AdminKeyBalance(
                account_id=row.account_id,
                telegram_username=row.telegram_username,
                **_key_verify_from_probe(row.probe).model_dump(),
            )
            for row in rows
        ]
    )


async def load_key_history() -> AdminKeyHistory:
    """Закрытые заявки и аудит выдач — то, чего не видно в очереди «ждут ключ»."""
    probe = _Probe()
    closed = await _fetch(
        "select r.id, r.account_id, a.telegram_username, r.status, r.requested_at, r.note, "
        "       r.resolved_at, r.resolved_by, resolver.telegram_username as resolver_username "
        "from openrouter_key_requests r "
        "join accounts a on a.id = r.account_id "
        "left join accounts resolver on resolver.id = r.resolved_by "
        "where r.status in ('rejected', 'fulfilled') "
        "order by r.resolved_at desc nulls last, r.id desc "
        "limit 50",
        name="история заявок",
        probe=probe,
    )
    audit_rows = await _fetch(
        "select a.id, a.at, a.actor_id, actor.telegram_username as actor_username, "
        "       a.action, a.target_id, target.telegram_username as target_username, a.details "
        "from admin_audit a "
        "left join accounts actor on actor.id = a.actor_id "
        "left join accounts target on target.id = a.target_id "
        "where a.action in ('key_issue', 'key_revoke', 'key_reject') "
        "order by a.at desc, a.id desc "
        "limit 50",
        name="аудит ключей",
        probe=probe,
    )
    return AdminKeyHistory(
        items=[_key_request_from_row(r) for r in closed],
        audit=[_audit_row_from_row(r) for r in audit_rows],
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def load_tasks(
    *, status: str = "", kind: str = "", limit: int = DEFAULT_TASK_LIMIT
) -> AdminTasks:
    """Очередь background_tasks за последние 48 часов (раздел «Действия»).

    Группы — (kind, status, reason); `limit` режет только `by_reason`, чтобы «Все»
    не вываливало тысячи строк в DOM. Счётчики `by_status` — по тому же окну.
    """
    capped = min(max(limit, 1), MAX_TASK_LIMIT)
    status_filter = status if status in TASK_STATUS_VALUES else ""
    kind_filter = kind.strip()
    probe = _Probe()
    window_sql = "updated_at >= now() - make_interval(hours => $1)"
    status_rows = await _fetch(
        f"select status, count(*)::int as n from background_tasks "
        f"where {window_sql} group by status",
        TASK_WINDOW_HOURS,
        name="глубина очереди",
        probe=probe,
    )
    kind_rows = await _fetch(
        f"select kind, status, count(*)::int as n from background_tasks "
        f"where {window_sql} group by kind, status",
        TASK_WINDOW_HOURS,
        name="очередь по виду",
        probe=probe,
    )
    # Items — запас под раскрытие групп текущей страницы; окно 48ч держит объём.
    item_cap = min(MAX_TASK_LIMIT, max(capped * 5, capped))
    item_rows = await _fetch(
        "select t.*, count(*) over ()::int as total_count "
        "from background_tasks t "
        "where t.updated_at >= now() - make_interval(hours => $1) "
        "  and ($2 = '' or t.status = $2) and ($3 = '' or t.kind = $3) "
        "order by case t.status "
        "  when 'failed' then 0 when 'running' then 1 when 'pending' then 2 "
        "  when 'cancelled' then 3 else 4 end, "
        "  t.updated_at desc nulls last, t.id desc "
        "limit $4",
        TASK_WINDOW_HOURS,
        status_filter,
        kind_filter,
        item_cap,
        name="список задач",
        probe=probe,
    )
    reasons_total_row = await _fetchrow(
        "select count(*)::int as n from ("
        "  select 1 from background_tasks "
        "  where updated_at >= now() - make_interval(hours => $1) "
        "    and ($2 = '' or status = $2) and ($3 = '' or kind = $3) "
        "  group by kind, status, left(coalesce(last_error, ''), $4)"
        ") groups",
        TASK_WINDOW_HOURS,
        status_filter,
        kind_filter,
        TASK_REASON_LEN,
        name="число групп очереди",
        probe=probe,
    )
    reason_rows = await _fetch(
        "select kind, status, left(coalesce(last_error, ''), $4) as reason, "
        "count(*)::int as n, "
        "max(coalesce(finished_at, updated_at, created_at)) as last_finished_at, "
        "min(coalesce(finished_at, updated_at, created_at)) as first_finished_at "
        "from background_tasks "
        "where updated_at >= now() - make_interval(hours => $1) "
        "  and ($2 = '' or status = $2) and ($3 = '' or kind = $3) "
        "group by 1, 2, 3 "
        "order by n desc, kind, status, reason "
        "limit $5",
        TASK_WINDOW_HOURS,
        status_filter,
        kind_filter,
        TASK_REASON_LEN,
        capped,
        name="очередь по причине",
        probe=probe,
    )
    by_kind_map: dict[str, AdminTaskKindCount] = {}
    for row in kind_rows:
        name = str(row.get("kind") or "без вида")
        bucket = by_kind_map.setdefault(name, AdminTaskKindCount(kind=name))
        st = str(row.get("status") or "")
        n = int(row.get("n") or 0)
        if st in TASK_STATUS_VALUES:
            setattr(bucket, st, getattr(bucket, st) + n)
        bucket.total += n
    by_kind = sorted(
        by_kind_map.values(),
        key=lambda item: (-item.failed, -item.running, -item.pending, item.kind),
    )
    return AdminTasks(
        by_status=_queue_from_rows(status_rows),
        by_kind=by_kind,
        by_reason=[
            AdminTaskReasonCount(
                kind=str(r.get("kind") or "без вида"),
                status=str(r.get("status") or ""),
                reason=str(r.get("reason") or ""),
                count=int(r.get("n") or 0),
                last_finished_at=r.get("last_finished_at"),
                first_finished_at=r.get("first_finished_at"),
            )
            for r in reason_rows
        ],
        items=[_task_detail_from_row(r) for r in item_rows],
        total=int(item_rows[0].get("total_count") or 0) if item_rows else 0,
        reasons_total=int((reasons_total_row or {}).get("n") or 0),
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def load_tables() -> AdminTables:
    """Сколько занимают ключевые таблицы — без psql (Этап 7.3)."""
    probe = _Probe()
    size_row = await _fetchrow(
        "select pg_database_size(current_database())::bigint as size",
        name="размер postgres",
        probe=probe,
    )
    rows = await _fetch(
        "select c.relname as name, "
        "pg_total_relation_size(c.oid)::bigint as bytes, "
        "pg_stat_get_live_tuples(c.oid)::bigint as approx_rows "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' "
        "  and c.relname = any($1::text[]) "
        "order by pg_total_relation_size(c.oid) desc",
        list(_TABLE_SIZE_NAMES),
        name="размеры таблиц",
        probe=probe,
    )
    db_size = size_row.get("size") if size_row else None
    return AdminTables(
        items=[
            AdminTableSize(
                name=str(r.get("name") or ""),
                bytes=int(r.get("bytes") or 0),
                approx_rows=int(r["approx_rows"]) if r.get("approx_rows") is not None else None,
            )
            for r in rows
        ],
        database_bytes=int(db_size) if db_size is not None else None,
        degraded=probe.degraded,
        degraded_reason=probe.reason,
    )


async def retry_task(task_id: int, *, actor_id: int) -> AdminTaskDetail:
    record = await get_runtime().retry_task(task_id)
    if record is None:
        raise AdminError("Нельзя перезапустить эту задачу")
    await _log_action(
        "task_retry",
        actor_id,
        target_account_id=record.account_id,
        task_id=record.id,
        kind=record.kind,
    )
    return _task_detail_from_record(record)


async def cancel_task(task_id: int, *, actor_id: int) -> AdminTaskDetail:
    record = await get_runtime().cancel_task(task_id)
    if record is None:
        raise AdminError("Нельзя отменить завершённую задачу")
    await _log_action(
        "task_cancel",
        actor_id,
        target_account_id=record.account_id,
        task_id=record.id,
        kind=record.kind,
    )
    return _task_detail_from_record(record)


async def retry_failed_of_kind(kind: str, *, actor_id: int, reason: str = "") -> int:
    cleaned = kind.strip()
    if not cleaned:
        raise AdminError("Нужен вид задач для перезапуска")
    needle = reason[:TASK_REASON_LEN]
    n = await get_runtime().retry_failed_of_kind(cleaned, reason=needle)
    await _log_action("task_retry", actor_id, kind=cleaned, reason=needle, n=n)
    return n


async def cancel_failed_of_kind(kind: str, *, actor_id: int, reason: str = "") -> int:
    cleaned = kind.strip()
    if not cleaned:
        raise AdminError("Нужен вид задач для отмены")
    needle = reason[:TASK_REASON_LEN]
    n = await get_runtime().cancel_failed_of_kind(cleaned, reason=needle)
    await _log_action("task_cancel", actor_id, kind=cleaned, reason=needle, n=n)
    return n


async def reclaim_stuck_tasks(*, actor_id: int) -> int:
    n = await get_runtime().reclaim_stuck()
    await _log_action("task_reclaim", actor_id, n=n)
    return n


async def purge_logs(*, days: int, actor_id: int) -> int:
    """Удалить copilot_logs строго старше окна. Без cron — кнопка в панели (Этап 7.3)."""
    if days not in LOG_PURGE_DAYS:
        raise AdminError("Окно уборки — 30, 60 или 90 дней")
    try:
        status = await get_pool().execute(
            "delete from copilot_logs where ts < now() - make_interval(days => $1::int)",
            days,
        )
    except Exception as exc:
        _note_query_failure("уборка логов", exc, None)
        raise AdminError("Не удалось удалить логи", status=503) from exc
    n = _exec_rowcount(status)
    await _log_action("logs_purge", actor_id, days=days, deleted=n)
    return n


async def note_friendships_repair(*, actor_id: int) -> None:
    """Аудит кнопки «Починить дружбы». Сам проход живёт в career — platform его не импортирует."""
    await _log_action("friendships_repair", actor_id)


_EXT_CONFIG_SECTIONS = ("flags", "tuning", "apply_selectors", "parse_selectors", "text_signals")


def _extension_config_dict(cfg: Any) -> dict[str, Any]:
    return {
        "version": cfg.version,
        "origin": cfg.origin,
        "updated_at": cfg.updated_at.isoformat(),
        "flags": cfg.flags,
        "tuning": cfg.tuning,
        "apply_selectors": cfg.apply_selectors,
        "parse_selectors": cfg.parse_selectors,
        "text_signals": cfg.text_signals,
        "issues": list(cfg.issues),
    }


async def get_extension_runtime_config_admin() -> dict[str, Any]:
    """Текущий merged рантайм-конфиг расширения + плоский dump для редактирования."""
    from core.domains.opportunities.extension_runtime_config import get_extension_runtime_config

    return _extension_config_dict(await get_extension_runtime_config())


async def set_extension_runtime_config_admin(
    payload: dict[str, Any], *, actor_id: int
) -> dict[str, Any]:
    """Записать оверрайд рантайм-конфига расширения (флаги / тюнинг / селекторы отклика и
    разбора / текстовые сигналы).

    Пустой оверрайд (`{}` или все секции пустые) — снять оверрайд, вернуться на репозиторный
    дефолт. Валидация мягкая на уровне домена (неизвестное отбрасывается, числа клампятся,
    регекс в селекторе не принимается), замечания возвращаются в `issues` — оператор видит,
    что проигнорено.
    """
    from core.domains.opportunities.extension_runtime_config import (
        SETTINGS_KEY,
        get_extension_runtime_config,
        reset_extension_runtime_config_cache,
        set_extension_runtime_config_override,
    )

    if not isinstance(payload, dict):
        raise AdminError("Ожидается объект с секциями " + " / ".join(_EXT_CONFIG_SECTIONS))
    unknown = set(payload) - {*_EXT_CONFIG_SECTIONS, "version", "updated_at", "origin"}
    if unknown:
        raise AdminError(f"Лишние ключи: {', '.join(sorted(unknown))}")

    sections = {k: payload.get(k) or {} for k in _EXT_CONFIG_SECTIONS}
    if not any(sections.values()):
        try:
            await get_pool().execute("delete from app_settings where key = $1", SETTINGS_KEY)
        except Exception as exc:
            raise AdminError("Не удалось снять оверрайд", status=503) from exc
        reset_extension_runtime_config_cache()
        await _log_action("extension_runtime_config", actor_id, cleared=True)
        cfg = await get_extension_runtime_config()
    else:
        cfg = await set_extension_runtime_config_override(sections)
        await _log_action(
            "extension_runtime_config",
            actor_id,
            version=cfg.version,
            flags=sections["flags"],
            issues=len(cfg.issues),
        )
    return _extension_config_dict(cfg)


async def set_spend_alert(usd: float, *, actor_id: int) -> float:
    """Мягкий порог расхода на человека. 0 выключает сигнал; LLM не отсекаем (Этап 8.2)."""
    cleaned = parse_spend_alert_usd(usd)
    await set_setting(SPEND_ALERT_KEY, cleaned, account_id=None)
    await _log_action("spend_alert", actor_id, usd=cleaned)
    return cleaned


# --- Автопросмотр / автоотклик пользователя (вкладка «Автоматизация» в дровере) ---
# Домены auto_apply / discovery — чужой bounded context; импортируем лениво внутри функций,
# как `get_extension_runtime_config_admin` выше. Читаем/пишем мимо RLS (`account_scope` внутри
# доменных ручек сам ставит нужный account_id по явному аргументу).

_PIPELINE_PLATFORMS: tuple[str, ...] = ("hh", "getmatch", "habr")


def _discovery_brief_state(raw: Any, platform: str) -> str:
    """`discovery_runtime_state` jsonb → 'off'|'running'|'paused'|'idle' для строки таблицы."""
    if not isinstance(raw, dict):
        return "idle"
    entry = raw.get(platform)
    state = entry.get("state") if isinstance(entry, dict) else None
    if state == "running":
        return "running"
    if isinstance(state, str) and state.startswith("paused_"):
        return "paused"
    return "idle"


def _auto_apply_brief_state(
    config_raw: Any, tick_raw: Any, platform: str, *, tick_seconds: int
) -> str:
    """`auto_apply_config` + heartbeat → 'off'|'live'|'stale' (stale = включено, раннер молчит)."""
    enabled = (
        isinstance(config_raw, dict)
        and isinstance(config_raw.get(platform), dict)
        and config_raw[platform].get("enabled") is True
    )
    if not enabled:
        return "off"
    stamp = tick_raw.get("at") if isinstance(tick_raw, dict) else None
    if isinstance(stamp, str):
        try:
            last = datetime.fromisoformat(stamp)
        except ValueError:
            last = None
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - last).total_seconds()
            if age <= tick_seconds * 3:
                return "live"
    return "stale"


async def _extension_tick_seconds() -> int:
    from core.domains.opportunities.extension_runtime_config import get_extension_runtime_config

    cfg = await get_extension_runtime_config()
    return int(cfg.tuning.get("auto_apply_tick_minutes", 5)) * 60


async def _extension_discovery_tick_seconds() -> int:
    from core.domains.opportunities.extension_runtime_config import get_extension_runtime_config

    cfg = await get_extension_runtime_config()
    # discovery_tick_minutes может быть дробным (0.5 = alarm раз в 30с) — round, не int-обрезка.
    return max(1, round(float(cfg.tuning.get("discovery_tick_minutes", 1)) * 60))


async def _load_people_pipeline(
    account_ids: list[int], probe: _Probe
) -> dict[int, AdminPipelineBrief]:
    """Статус авто-процессов + счётчики 24ч для страницы таблицы «Люди» — батч, как спарклайн."""
    empty: dict[int, AdminPipelineBrief] = {aid: AdminPipelineBrief() for aid in account_ids}
    if not account_ids:
        return empty
    tick_seconds = await _extension_tick_seconds()

    applied_rows = await _fetch(
        "select account_id, count(*)::int as n from application_stages "
        "where account_id = any($1::bigint[]) and source like 'auto_apply_%' "
        "and changed_at >= now() - interval '24 hours' group by account_id",
        account_ids,
        name="автооткликов 24ч",
        probe=probe,
    )
    viewed_rows = await _fetch(
        "select account_id, "
        "  coalesce(sum(coalesce((fields->>'opened')::int, 0)), 0)::int as n "
        "from copilot_logs "
        "where account_id = any($1::bigint[]) and event = 'АВТОПРОСМОТР' "
        "  and ts >= now() - interval '24 hours' group by account_id",
        account_ids,
        name="автопросмотров 24ч",
        probe=probe,
    )
    setting_rows = await _fetch(
        "select account_id, key, value from account_settings "
        "where account_id = any($1::bigint[]) "
        "  and key in ('auto_apply_config', 'discovery_runtime_state', 'auto_apply_runner_tick')",
        account_ids,
        name="статус авто-процессов",
        probe=probe,
    )

    def _by_account(rows: list[dict[str, Any]]) -> dict[int, int]:
        out: dict[int, int] = {}
        for r in rows:
            aid = r.get("account_id")
            if aid is None:
                continue
            out[int(aid)] = int(r.get("n") or 0)
        return out

    applied_by = _by_account(applied_rows)
    viewed_by = _by_account(viewed_rows)
    settings_by: dict[int, dict[str, Any]] = {}
    for row in setting_rows:
        aid = row.get("account_id")
        key = row.get("key")
        if aid is None or not isinstance(key, str):
            continue
        settings_by.setdefault(int(aid), {})[key] = row.get("value")

    for aid in account_ids:
        s = settings_by.get(aid, {})
        cfg_raw = s.get("auto_apply_config")
        disc_raw = s.get("discovery_runtime_state")
        tick_raw = s.get("auto_apply_runner_tick")
        empty[aid] = AdminPipelineBrief(
            discovery={p: _discovery_brief_state(disc_raw, p) for p in _PIPELINE_PLATFORMS},
            auto_apply={
                p: _auto_apply_brief_state(cfg_raw, tick_raw, p, tick_seconds=tick_seconds)
                for p in _PIPELINE_PLATFORMS
            },
            viewed_24h=viewed_by.get(aid, 0),
            applied_24h=applied_by.get(aid, 0),
        )
    return empty


async def load_user_pipeline(account_id: int) -> AdminUserPipeline:
    """Полная картина авто-процессов пользователя для вкладки «Автоматизация» в дровере."""
    from core.domains.opportunities import discovery_session as ds
    from core.domains.opportunities.discovery_session import discovery_daily_hard_cap
    from core.domains.pipeline.auto_apply import (
        auto_apply_daily_hard_cap,
        count_today,
        get_auto_apply_config,
        preview_queue,
    )
    from core.domains.pipeline.auto_apply.runtime_state import get_last_tick

    row = await _fetchrow(_USER_BY_ID_SQL, account_id, name="карточка человека (пайплайн)")
    if row is None:
        raise AdminError("Аккаунт не найден", status=404)

    aa_config = await get_auto_apply_config(account_id=account_id)
    d_config = await ds.get_discovery_config(account_id=account_id)
    tick_seconds = await _extension_tick_seconds()

    platforms: list[AdminPipelinePlatform] = []
    for p in _PIPELINE_PLATFORMS:
        aa = aa_config.platform(p)  # type: ignore[arg-type]
        dc = d_config.platform(p)  # type: ignore[arg-type]
        try:
            dstatus = await ds.get_discovery_status(p, account_id=account_id)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — статус декоративен
            logger.debug("admin pipeline: discovery status %s/%s: %s", account_id, p, exc)
            dstatus = ds.DiscoveryStatus(platform=p)  # type: ignore[arg-type]
        preview = await preview_queue(p, account_id=account_id)  # type: ignore[arg-type]
        pending = sum(
            1
            for j in (*preview.auto, *preview.manual_review)
            if j.anketa and j.anketa.get("status") == "pending"
        )
        platforms.append(
            AdminPipelinePlatform(
                platform=p,
                discovery_state=dstatus.state,
                # 2026-08-28: жёсткий суточный потолок, а не ручка пользователя (`dc.daily_cap`
                # больше не читается).
                discovery_daily_cap=discovery_daily_hard_cap(p),
                discovery_used_today=dstatus.daily_used,
                discovery_opened_session=dstatus.opened,
                discovery_search_urls=len([u for u in dc.search_urls if u.strip()]),
                auto_apply_enabled=aa.enabled,
                auto_apply_daily_cap=auto_apply_daily_hard_cap(p),  # type: ignore[arg-type]
                auto_apply_min_score=aa.min_score,
                auto_apply_manual_band=aa.manual_review_band,
                auto_apply_dry_run=aa.dry_run or aa.require_confirmation,
                queue_auto=len(preview.auto),
                queue_manual=len(preview.manual_review),
                pending_confirm=pending,
                applied_today=await count_today(p, account_id=account_id),  # type: ignore[arg-type]
            )
        )

    aa_tick = await get_last_tick(account_id=account_id)
    d_tick = await ds.get_last_runner_tick(account_id=account_id)
    aa_tick_at = _runner_tick_at(aa_tick)
    disc_tick_seconds = await _extension_discovery_tick_seconds()
    return AdminUserPipeline(
        platforms=platforms,
        discovery_last_tick_at=_runner_tick_at(d_tick),
        auto_apply_last_tick_at=aa_tick_at,
        auto_apply_next_tick_eta=(
            aa_tick_at + timedelta(seconds=tick_seconds) if aa_tick_at else None
        ),
        tick_seconds=tick_seconds,
        discovery_tick_seconds=disc_tick_seconds,
        any_discovery_running=any(pl.discovery_state == "running" for pl in platforms),
        any_auto_apply_enabled=any(pl.auto_apply_enabled for pl in platforms),
    )


async def pause_user_auto_apply(account_id: int, *, actor_id: int) -> None:
    """Оператор гасит автоотклики пользователя (kill switch, вместе с сессиями автопросмотра)."""
    from core.app.scenarios.auto_apply import pause_all

    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    await pause_all(account_id=account_id)
    await _log_action("auto_apply_pause", actor_id, target_account_id=account_id)


async def resume_user_auto_apply(account_id: int, *, actor_id: int) -> None:
    """Оператор возобновляет автоотклики пользователя (`enabled=True` на всех площадках)."""
    from core.app.scenarios.auto_apply import resume_all

    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    await resume_all(account_id=account_id)
    await _log_action("auto_apply_resume", actor_id, target_account_id=account_id)


async def clear_user_auto_apply_queue(account_id: int, *, actor_id: int) -> int:
    """Оператор чистит очередь автооткликов пользователя (пропускает всё видимое в превью)."""
    from core.app.scenarios.auto_apply import clear_queue

    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    cleared = await clear_queue(account_id=account_id)
    await _log_action("auto_apply_clear", actor_id, target_account_id=account_id, cleared=cleared)
    return cleared


async def stop_user_discovery(account_id: int, *, platform: str | None, actor_id: int) -> list[str]:
    """Оператор останавливает автопросмотр пользователя — одну площадку или все три."""
    from core.domains.opportunities import discovery_session as ds

    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    targets = [platform] if platform in _PIPELINE_PLATFORMS else list(_PIPELINE_PLATFORMS)
    stopped: list[str] = []
    for p in targets:
        try:
            status = await ds.get_discovery_status(p, account_id=account_id)  # type: ignore[arg-type]
            if status.state == "idle":
                continue
            await ds.stop_session(p, account_id=account_id)  # type: ignore[arg-type]
            stopped.append(p)
        except Exception as exc:  # noqa: BLE001 — одна площадка не роняет остальные
            logger.warning("admin: стоп автопросмотра %s/%s не удался: %s", account_id, p, exc)
    await _log_action("discovery_stop", actor_id, target_account_id=account_id, platforms=stopped)
    return stopped


async def clear_user_discovery_log(account_id: int, *, actor_id: int) -> None:
    """Оператор чистит лог автопросмотра пользователя по всем площадкам (сессии не трогает)."""
    from core.domains.opportunities import discovery_session as ds

    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    for p in _PIPELINE_PLATFORMS:
        try:
            await ds.clear_events(p, account_id=account_id)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.warning("admin: очистка лога автопросмотра %s/%s: %s", account_id, p, exc)
    await _log_action("discovery_clear_log", actor_id, target_account_id=account_id)


__all__ = [
    "DEFAULT_LOG_LEVELS",
    "MAX_LOG_LIMIT",
    "MAX_LOG_WINDOW",
    "MIN_LOG_QUERY_LEN",
    "cancel_failed_of_kind",
    "cancel_task",
    "clear_user_auto_apply_queue",
    "clear_user_discovery_log",
    "compile_log_query",
    "disable_user",
    "enable_user",
    "enqueue_admin_telegram",
    "forecast_month_usd",
    "issue_user_key",
    "load_attention",
    "load_audit_page",
    "load_key_history",
    "load_logs",
    "load_people",
    "load_spend",
    "load_summary",
    "load_support_thread",
    "load_tables",
    "load_tasks",
    "load_user_detail",
    "load_user_diagnosis",
    "load_user_pipeline",
    "note_friendships_repair",
    "pause_user_auto_apply",
    "parse_log_levels",
    "parse_spend_alert_usd",
    "people_sort_keys",
    "purge_logs",
    "reclaim_stuck_tasks",
    "record_inbound_user_telegram",
    "refresh_key_balances",
    "reject_key_request",
    "resolve_log_window",
    "resume_user_auto_apply",
    "retry_failed_of_kind",
    "retry_task",
    "revoke_one_user_session",
    "revoke_user_key",
    "revoke_user_sessions",
    "search_profile_lines",
    "send_support_message",
    "set_spend_alert",
    "set_user_note",
    "set_user_role",
    "spend_sparkline_series",
    "stop_user_discovery",
    "user_log_bundle",
    "verify_stored_user_key",
    "verify_user_key",
]
