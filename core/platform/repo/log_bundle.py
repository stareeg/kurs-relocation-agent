"""Сборка zip-бандла логов аккаунта (админка и инцидент-экран).

Бандл читает владелец кода, а не пользователь: задача — по одному архиву понять, что человек
делал, где сломалось и в каком окружении. Поэтому внутри четыре файла разного назначения:

- ``manifest.json`` — шапка: когда собрано, за какое окно, чей аккаунт, сколько строк какого
  уровня, какие логгеры шумели, время первой/последней записи. Читается первой и сразу говорит,
  есть ли вообще смысл искать дальше;
- ``timeline.txt`` — вся выборка ПО ВОЗРАСТАНИЮ времени, одна строка = одно событие. Это
  «что происходило» в читаемом виде: HTTP-мутации, фон, LLM, фронтовые ошибки — одной лентой;
- ``errors.txt`` — только WARNING+ (те же строки, тот же порядок) со стектрейсом/полями:
  короткий файл, с которого начинается разбор инцидента;
- ``copilot_logs.json`` — сырые строки со всеми ``fields`` для машинного разбора/grep.
- ``llm_calls.json`` — последние LLM-вызовы аккаунта (фича, модель, токены, стоимость,
  тайминги, попал ли в кэш): без них «долго думает» и «дорого» не разобрать.

Строго по ``account_id``: записи без атрибуции (системный старт, фон без личности) не попадают
никому, включая владельца. Каждый источник best-effort: нет PG/таблицы → источник просто
отсутствует в архиве, сборка не падает.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import zipfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

from core.platform.db.pool import get_pool

# Окно по умолчанию. Трое суток, а не сутки: про баг обычно рассказывают не в ту же минуту,
# а «вчера что-то сломалось» — с окном в 24 часа архив к тому времени уже пустой.
DEFAULT_WINDOW_HOURS = 72
MAX_WINDOW_HOURS = 24 * 14

# Потолок на выборку, чтобы архив оставался читаемым (и не тянул мегабайты polling-строк).
_MAX_ROWS = 20_000
_MAX_LLM_ROWS = 500


def resolve_window_hours(hours: int | None) -> int:
    """Окно бандла в часах: None/мусор → дефолт, всё остальное зажимается в [1, MAX]."""
    if not hours or hours <= 0:
        return DEFAULT_WINDOW_HOURS
    return min(hours, MAX_WINDOW_HOURS)


async def _fetch_logs(account_id: int, since: datetime) -> list[dict[str, Any]]:
    """Строки `copilot_logs` своего аккаунта за окно, ПО ВОЗРАСТАНИЮ времени (порядок чтения)."""
    try:
        pool = get_pool()
        rows = await pool.fetch(
            "select ts, level, logger, event, task_id, msg, fields "
            "from copilot_logs where account_id = $1 and ts >= $2 "
            "order by ts asc limit $3",
            account_id,
            since,
            _MAX_ROWS,
        )
    except Exception:  # noqa: BLE001 — бандл собирается из того, что есть
        return []
    return [dict(r) for r in rows]


async def _fetch_llm_calls(account_id: int, since: datetime) -> list[dict[str, Any]]:
    """Последние LLM-вызовы аккаунта: чем занят бюджет и почему ответ шёл долго."""
    try:
        pool = get_pool()
        rows = await pool.fetch(
            "select ts, agent as feature, model, tokens_in, tokens_out, "
            "cost_usd::float8 as cost_usd, ttfb_ms, total_ms, queue_ms, attempt, cache_hit "
            "from llm_usage where account_id = $1 and ts >= $2 "
            "order by ts desc limit $3",
            account_id,
            since,
            _MAX_LLM_ROWS,
        )
    except Exception:  # noqa: BLE001 — таблицы может не быть (PG лежит) — не повод рушить архив
        return []
    return [dict(r) for r in rows]


def _fmt_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "")


def _fmt_fields(fields: Any) -> str:
    """`fields` записи → компактный хвост строки. Пусто/битое → пустая строка."""
    if not fields:
        return ""
    data = fields
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return f" | {data}"
    if not isinstance(data, dict):
        return f" | {data}"
    # stack показываем отдельным блоком в errors.txt, в ленте он рвёт читаемость.
    pairs = [f"{k}={v}" for k, v in data.items() if k != "stack" and v is not None]
    return " | " + " ".join(pairs) if pairs else ""


def _timeline_line(row: dict[str, Any]) -> str:
    event = row.get("event")
    tag = f"[{event}] " if event else ""
    return (
        f"{_fmt_ts(row.get('ts'))} {str(row.get('level') or 'INFO'):<7} "
        f"{row.get('logger') or '-'} {tag}{row.get('msg') or ''}{_fmt_fields(row.get('fields'))}"
    )


def _timeline_text(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(за это окно записей нет)\n"
    return "\n".join(_timeline_line(r) for r in rows) + "\n"


def _errors_text(rows: list[dict[str, Any]]) -> str:
    """Только WARNING+ со стектрейсом — файл, с которого начинается разбор инцидента."""
    bad = [r for r in rows if str(r.get("level") or "").upper() in {"WARNING", "ERROR", "CRITICAL"}]
    if not bad:
        return "(ошибок и предупреждений за это окно нет)\n"
    chunks: list[str] = []
    for row in bad:
        chunks.append(_timeline_line(row))
        fields = row.get("fields")
        if isinstance(fields, str):
            try:
                fields = json.loads(fields)
            except ValueError:
                fields = None
        stack = fields.get("stack") if isinstance(fields, dict) else None
        if stack:
            chunks.append("    " + str(stack).replace("\n", "\n    "))
    return "\n".join(chunks) + "\n"


def _manifest(
    *, account_id: int, window_hours: int, rows: list[dict[str, Any]], llm_calls: int
) -> dict[str, Any]:
    levels = Counter(str(r.get("level") or "INFO").upper() for r in rows)
    loggers = Counter(str(r.get("logger") or "-") for r in rows)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "window_hours": window_hours,
        "account_id": account_id,
        "rows": len(rows),
        "truncated": len(rows) >= _MAX_ROWS,
        "first_ts": _fmt_ts(rows[0].get("ts")) if rows else None,
        "last_ts": _fmt_ts(rows[-1].get("ts")) if rows else None,
        "levels": dict(levels.most_common()),
        "top_loggers": dict(loggers.most_common(15)),
        "llm_calls": llm_calls,
        "server": {
            # Коммит проставляет деплой, если пробросит переменную; иначе просто null —
            # лучше явное «неизвестно», чем догадки о том, какой код собрал архив.
            "git_sha": os.getenv("COPILOT_GIT_SHA") or None,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")


async def build_log_bundle_zip(account_id: int, *, window_hours: int | None = None) -> bytes:
    """Собрать zip-бандл в памяти и вернуть готовые байты (состав — см. докстринг модуля)."""
    hours = resolve_window_hours(window_hours)
    since = datetime.now(UTC) - timedelta(hours=hours)
    rows = await _fetch_logs(account_id, since)
    llm_calls = await _fetch_llm_calls(account_id, since)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "manifest.json",
            _json_bytes(
                _manifest(
                    account_id=account_id,
                    window_hours=hours,
                    rows=rows,
                    llm_calls=len(llm_calls),
                )
            ),
        )
        zf.writestr("timeline.txt", _timeline_text(rows).encode("utf-8"))
        zf.writestr("errors.txt", _errors_text(rows).encode("utf-8"))
        zf.writestr("copilot_logs.json", _json_bytes(rows))
        zf.writestr("llm_calls.json", _json_bytes(llm_calls))
    return buf.getvalue()
