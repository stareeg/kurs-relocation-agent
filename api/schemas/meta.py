"""Транспортные схемы API: meta."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

# --- Захват фронтовых ошибок: POST /api/logs/frontend, ring-buffer → copilot_logs ---


class FrontendLogEntry(BaseModel):
    """Одна запись из клиентского ring-буфера error-capture.ts, rum.ts или расширения.

    `kind` различает источник: window.onerror / unhandledrejection / http / network /
    boundary / extension_parse / rum_lcp|rum_inp|rum_ttfb|rum_first_token|rum_done.
    `level`: ERROR | WARNING | INFO (RUM — INFO).
    """

    ts: str
    level: str = "ERROR"
    kind: str
    message: str
    stack: str | None = None
    url: str | None = None
    endpoint: str | None = None
    status: int | None = None
    duration_ms: float | None = None
    # Шаг 6 парсера hh: метод/версия конфига из parse-health. Без HTML страницы.
    parse_method: str | None = None
    config_version: int | None = None
    config_origin: str | None = None


class FrontendLogBatch(BaseModel):
    entries: list[FrontendLogEntry]


# --- Meta (7.4 / D2 / D3): формальная синхронизация источников вакансий бэк↔фронт ---


class JobSourceItem(BaseModel):
    """Один канонический `jobs.source` + его UI-группа.

    Бэк — единственный источник истины для перечня `ALL_JOB_SOURCES`; фронт генерирует
    `HH_SOURCES` из этого списка вместо хардкода (D2). Группа `hh`/`getmatch`/`tg` — для
    фильтра и иконок (D3). При добавлении нового источника на бэке достаточно регенерации
    `schema.d.ts` — фронт подхватит автоматически.
    """

    source: str
    group: str


class JobSourcesResponse(BaseModel):
    """Справочник источников вакансий для фронта (фильтр по источнику)."""

    sources: list[JobSourceItem]
    groups: list[str]


# --- Подсказки городов проживания (Э0.2): свои данные, без LLM ---


class CitySuggestion(BaseModel):
    """Один город для автокомплита «Город проживания».

    `source`: jobs — из `jobs.work_city`; resume — из `experience[].area`.
    Страна/зона пустые, если город не в справочнике `kernel.timezones` — не угадываем.
    """

    city: str
    country: str = ""
    timezone: str = ""
    utc_offset: str = ""
    overlap_emea: int | None = None
    source: str = "jobs"


class CitiesResponse(BaseModel):
    """Подсказки из своих вакансий и опыта. Пустой `items` на холодном старте — норма."""

    items: list[CitySuggestion]


# --- Установка расширения: страница «Расширение» показывает готовый путь ---


class ExtensionSetupResponse(BaseModel):
    """Данные для страницы установки расширения: готовность сборки и версионность.

    `extension_dir` — путь на диске сервера (фронт больше не показывает, EX-14, но поле
    сохранено для совместимости). `latest_version` — версия из `extension/manifest.json`
    (канон: именно её собрал бэкенд). `installed_version` — версия, которую реально
    использует этот аккаунт (захватывается из заголовка `X-Extension-Version` при первом
    запросе расширения); `None`, если расширение ещё ни разу не обращалось или версию не
    присылало. Фронт по `installed_version < latest_version` показывает «вышла новая версия».
    """

    extension_dir: str
    dist_ready: bool
    latest_version: str | None = None
    installed_version: str | None = None


# --- Фоновые задачи: витрина очереди platform/tasks ---


class BackgroundTaskItem(BaseModel):
    """Одна строка очереди для UI «Параметры»."""

    id: int
    kind: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    idempotency_key: str | None = None
    run_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str = ""
    created_at: datetime


class BackgroundTasksResponse(BaseModel):
    items: list[BackgroundTaskItem]


__all__ = [
    "BackgroundTaskItem",
    "BackgroundTasksResponse",
    "CitiesResponse",
    "CitySuggestion",
    "ExtensionSetupResponse",
    "FrontendLogEntry",
    "FrontendLogBatch",
    "JobSourceItem",
    "JobSourcesResponse",
]
