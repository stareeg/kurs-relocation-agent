"""Централизованная настройка логирования.

Одна точка входа `setup_logging()` поднимает:
- красивую консоль через rich (ключевые точки видно сразу, цветной тег категории слева);
- файл `logs/copilot.log` — вся история с ротацией;
- файл `logs/errors.log` — только предупреждения и ошибки;
- приглушение шумных сторонних логгеров (httpx, aiogram и пр.).

Структурная витрина для UI (таблица Postgres) и spool-буфер живут отдельно и
берут сериализацию записи из `record_to_dict()`. Корреляция строк по задаче — через
`task_id_var` (наполняется на шаге L5).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from core.config import current_account_id, get_settings

# --- Корреляция: id текущей задачи протекает по async-вызовам (наполняется на L5) ---
task_id_var: ContextVar[str] = ContextVar("task_id", default="-")


def set_task_id(task_id: str) -> Any:
    """Пометить текущий контекст id задачи; вернуть токен для последующего сброса."""
    return task_id_var.set(task_id)


def reset_task_id(token: Any) -> None:
    """Откатить task_id к прежнему значению по токену из set_task_id."""
    task_id_var.reset(token)


# --- Категории ключевых точек: тег + его цвет в консоли ---
EVENT_STYLES: dict[str, str] = {
    "ЗАПУСК": "bold green",
    "LLM": "bold cyan",
    "БД": "bold blue",
    "ПАМЯТЬ": "bold magenta",
    "СОБЫТИЕ": "bold bright_magenta",
    "ИНГЕСТ": "bold yellow",
    "ЗАДАЧА": "bold white",
    "HITL": "bold dark_orange",
    "ОШИБКА": "bold red",
    "ФРОНТ": "bold red",
    "RUM": "bold bright_cyan",
    "РАСШИРЕНИЕ": "bold yellow",
    "HTTP": "dim",
    "АВТОРИЗАЦИЯ": "bold bright_yellow",
    "АДМИН": "bold bright_red",
}

# Шумные сторонние логгеры: их INFO/DEBUG топит полезные строки, держим на WARNING.
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "openai",
    "aiogram.event",
    "urllib3",
    "asyncio",
)

_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [task=%(task_id)s] %(message)s"

# Штатные поля LogRecord — всё, что вне их, считаем доп. полями (extra) записи.
_RESERVED = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
    "task_id",
    "account_id",
    "event",
}


class TaskIdFilter(logging.Filter):
    """Вшивает task_id из контекста в каждую запись (для файла и витрины UI)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "task_id"):
            record.task_id = task_id_var.get()
        return True


class AccountIdFilter(logging.Filter):
    """Вшивает account_id из per-request/per-task ContextVar (M6, plans/multitenancy_gaps_
    2026_08_06.md §3.9) — тот же приём, что `TaskIdFilter`. Источник — `core.config.
    current_account_id()`, выставляемый HTTP/бот-middleware на весь запрос/апдейт и воркером
    очереди на время account-задачи (`core.app.background`); вне такого контекста — `None`
    (система/CLI), запись не попадёт ни в чей персональный бандл."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "account_id"):
            record.account_id = current_account_id()
        return True


def record_to_dict(record: logging.LogRecord) -> dict[str, Any]:
    """Запись лога → сериализуемый dict. Источник для spool и витрины PG (шаг L6)."""
    data: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
        "level": record.levelname,
        "logger": record.name,
        "event": getattr(record, "event", None),
        "task_id": getattr(record, "task_id", task_id_var.get()),
        "account_id": getattr(record, "account_id", None) or current_account_id(),
        "msg": record.getMessage(),
    }
    fields: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _RESERVED:
            continue
        try:
            json.dumps(value)
            fields[key] = value
        except (TypeError, ValueError):
            fields[key] = str(value)
    if fields:
        data["fields"] = fields
    return data


def ensure_utf8_console() -> None:
    """Windows-консоль по умолчанию открывает stdout/stderr в cp1251/866 — кириллица и эмодзи
    в print/логах падают UnicodeEncodeError или превращаются в мусор (migrate, dump_openapi).
    Правка для точек входа: `setup_logging()`, CLI вроде `python -m api.dump_openapi`."""
    if sys.platform != "win32":
        return
    os.environ.setdefault("PYTHONUTF8", "1")
    for stream in (sys.stdout, sys.stderr):
        # Поток без reconfigure (перехвачен тестом и т.п.) — не критично.
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(Exception):
                reconfigure(encoding="utf-8")


# Старое имя — внутренние вызовы / импорты до FR2-65.
_ensure_utf8_console = ensure_utf8_console


def _to_level(value: str, default: int) -> int:
    """Имя уровня ('INFO') → число; неизвестное имя → default."""
    resolved = logging.getLevelName(value.upper())
    return resolved if isinstance(resolved, int) else default


def _build_console_handler(level: int) -> logging.Handler:
    """rich-консоль с цветным тегом категории; если rich недоступен — обычный поток."""
    try:
        from rich.console import Console
        from rich.logging import RichHandler
        from rich.text import Text
    except ImportError:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        return handler

    class CopilotRichHandler(RichHandler):
        """RichHandler, который красит тег категории в начале сообщения."""

        def render_message(self, record: logging.LogRecord, message: str):  # type: ignore[override]
            text = super().render_message(record, message)
            ev = getattr(record, "event", "") or ""
            style = EVENT_STYLES.get(ev)
            if style and isinstance(text, Text) and message.startswith(ev):
                text.stylize(style, 0, len(ev))
            return text

    handler = CopilotRichHandler(
        level=level,
        console=Console(),
        show_time=True,
        show_level=True,
        show_path=False,
        markup=False,
        rich_tracebacks=True,
        omit_repeated_times=False,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    return handler


def _build_file_handler(path: Path, level: int, max_mb: int, backups: int) -> logging.Handler:
    handler = RotatingFileHandler(
        path, maxBytes=max_mb * 1024 * 1024, backupCount=backups, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    return handler


def setup_logging(
    level: str | None = None,
    file_level: str | None = None,
    log_dir: str | None = None,
) -> None:
    """Идемпотентно настроить логирование всей системы. Зовётся первой строкой main().

    Повторный вызов (например, бот и API в одном процессе) ничего не делает — хендлеры
    помечены атрибутом `_copilot` и не дублируются.
    """
    root = logging.getLogger()
    if any(getattr(h, "_copilot", False) for h in root.handlers):
        return

    ensure_utf8_console()
    settings = get_settings()
    console_level = _to_level(level or settings.log_level, logging.INFO)
    file_lvl = _to_level(file_level or settings.log_level_file, logging.DEBUG)

    logs_path = Path(log_dir or settings.log_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    task_filter = TaskIdFilter()
    account_filter = AccountIdFilter()
    handlers: list[logging.Handler] = []

    if settings.log_rich:
        handlers.append(_build_console_handler(console_level))
    else:
        plain = logging.StreamHandler()
        plain.setLevel(console_level)
        plain.setFormatter(logging.Formatter(_FILE_FORMAT))
        handlers.append(plain)

    handlers.append(
        _build_file_handler(
            logs_path / "copilot.log", file_lvl, settings.log_rotation_mb, settings.log_backups
        )
    )
    handlers.append(
        _build_file_handler(
            logs_path / "errors.log",
            logging.WARNING,
            settings.log_rotation_mb,
            settings.log_backups,
        )
    )

    # Витрина UI (шаг L6): хендлер-очередь INFO+. Фоновый писатель (PgLogSink) поднимается
    # в lifespan API и дренит её в Postgres; до того строки копятся в ограниченной очереди.
    try:
        from core.platform.observability.pg_sink import QueueLogHandler

        handlers.append(QueueLogHandler())
    except Exception:  # noqa: BLE001 — витрина не критична для консоли и файлов
        pass

    for handler in handlers:
        handler.addFilter(task_filter)
        handler.addFilter(account_filter)
        handler._copilot = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    # Root пропускает всё до самого подробного хендлера; реальная отсечка — на хендлерах.
    root.setLevel(min(console_level, file_lvl))

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Логгер для модуля. Тонкая обёртка над logging.getLogger ради единого импорта."""
    return logging.getLogger(name)


def event(
    logger: logging.Logger,
    category: str,
    msg: str,
    *args: Any,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Ключевая точка: цветной тег категории в консоли + поле `event` для витрины UI.

    Пример: event(log, "LLM", "ответ: %s, %d ток", model, tokens_out)
    Для предупреждений: event(log, "БД", "недоступен: %s", exc, level=logging.WARNING).
    Для падений с трассой: event(log, "ЗАДАЧА", "упала: %s", exc, level=ERROR, exc_info=True).
    Категория должна быть из EVENT_STYLES, иначе тег покажется без цвета.
    """
    logger.log(
        level, f"{category} {msg}", *args, exc_info=exc_info, extra={"event": category, **fields}
    )
