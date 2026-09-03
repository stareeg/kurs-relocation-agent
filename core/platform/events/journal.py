"""Журнал доменных событий в витрину `copilot_logs`.

Отдельной таблицы нет намеренно: витрина логов уже даёт то, ради чего журнал нужен — лента
с фильтром по типу, полями в `jsonb` и неблокирующей записью (хендлер кладёт строку в очередь,
`PgLogSink` батчит). Событие → одна строка INFO с категорией `СОБЫТИЕ`, именем события в
`fields.event_name` и его полями рядом.

Событие принимается структурно: `platform` не знает типов из `core.kernel.events`, ему хватает
класса объекта и необязательных `subject` / `to_fields()`.
"""

from __future__ import annotations

import logging
from typing import Any

from core.platform.observability.logging import event as log_event

logger = logging.getLogger("core.events")

#: Категория витрины (цвет — в `EVENT_STYLES`); попадает в `copilot_logs.event`.
CATEGORY = "СОБЫТИЕ"

#: Штатные атрибуты LogRecord: одноимённое поле события затрёт их и уронит logging.
_LOG_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "event",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "task_id",
        "taskName",
        "thread",
        "threadName",
    }
)


def _fields(evt: Any) -> dict[str, Any]:
    """Поля события для `copilot_logs.fields`; коллизии с полями LogRecord отбрасываем."""
    raw = getattr(evt, "to_fields", None)
    data = raw() if callable(raw) else {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k not in _LOG_RESERVED}


def log_domain_event(evt: Any) -> None:
    """Записать событие в витрину. Зовётся шиной как `journal`-колбэк (см. `core/app/wiring.py`)."""
    name = getattr(evt, "name", None) or type(evt).__name__
    subject = getattr(evt, "subject", "") or ""
    log_event(
        logger,
        CATEGORY,
        "%s%s",
        name,
        f" [{subject}]" if subject else "",
        event_name=name,
        subject=subject,
        **_fields(evt),
    )


__all__ = ["CATEGORY", "log_domain_event"]
