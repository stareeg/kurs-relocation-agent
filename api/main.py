"""FastAPI-приложение Career Copilot.

Транспорт для фронта, бота и расширения:
- POST /api/chat/stream — прямой SSE-стрим чата;
- POST /score — синхронный скоринг (путь расширения, X-API-Key);
- read-эндпоинты /api/jobs, /api/metrics, /api/session для фронта;
- /auth/* — вход по токену из Telegram-бота; /api/* и /score за require_account
  (web-токен: cookie/X-Auth-Token/X-API-Key — ИЛИ статический X-API-Key из .env).

Запуск: uv run uvicorn api.main:app --port 8000
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from api.config import get_settings
from api.errors import to_response
from api.routers import mount_routers
from api.security import (
    AUTH_COOKIE,
    client_ip,
    require_account,
    resolve_request_account,
    touch_account_last_seen,
)
from api.timing import REQUEST_ID_HEADER, SERVER_TIMING_HEADER, request_timing_middleware
from core.app import wire_default_ports
from core.app.background import start_background_runtime, stop_background_runtime
from core.config import (
    ConfigError,
    ensure_env_file,
    reset_current_account_id,
    set_current_account_id,
)
from core.config import get_settings as get_core_settings
from core.domains.profile.structured_store import load_resume_into_runtime
from core.kernel.errors import DomainError
from core.platform.db.pool import close_pool, init_pool
from core.platform.http import close_http_client, init_http_client, warmup_openrouter
from core.platform.llm.usage import set_default_usage_sink
from core.platform.observability import PgLogSink, event, set_default_log_sink, setup_logging
from core.platform.repo.settings import (
    load_openrouter_key_into_runtime,
    prime_runtime_openrouter_key_for_account,
)
from core.platform.repo.usage import PostgresUsageSink

logger = logging.getLogger(__name__)


def _configured_worker_count() -> int | None:
    """Сколько uvicorn-воркеров просили — из `--workers` в argv или `WEB_CONCURRENCY`.
    `None` — не задано (то есть один)."""
    argv = sys.argv
    if "--workers" in argv:
        idx = argv.index("--workers")
        if idx + 1 < len(argv):
            try:
                return int(argv[idx + 1])
            except ValueError:
                return 2
        return 2
    raw = (os.getenv("WEB_CONCURRENCY") or os.getenv("UVICORN_WORKERS") or "").strip()
    if raw.isdigit():
        return int(raw)
    return None


def _warn_if_multiple_workers() -> None:
    """Э20.5: невидимый несущий инвариант — API работает строго в один процесс.

    `core.domains.multiplayer.session._HUB` (живые столы, WS-партии «Хрюши и Волки»,
    таймеры фаз) держится в памяти процесса. С несколькими uvicorn-воркерами комнаты
    разъедутся по процессам, и WS-соединение попадёт не в тот воркер — стол «то работает,
    то нет», диагностика на день. Горизонтальное масштабирование этой нагрузке не нужно
    (десяток столов по ≤6 человек), но ломаться молча оно не должно. Подробнее —
    `core/domains/multiplayer/README.md`, раздел «Один воркер».
    """
    workers = _configured_worker_count()
    if workers is not None and workers > 1:
        event(
            logger,
            "ОШИБКА",
            "uvicorn запущен с %d воркерами — «Мультиплеер» (хаб столов в памяти процесса) "
            "работать не будет: WS-соединения размажутся по процессам. Нужен один воркер.",
            workers,
            level=logging.ERROR,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Поднять пул Postgres. Внешний сервис недоступен — не валим API."""
    # A-18: нет .env → короткий ConfigError со списком секретов, не dump модели.
    try:
        ensure_env_file()
    except ConfigError as exc:
        event(logger, "ОШИБКА", "%s", exc, level=logging.ERROR)
        raise
    setup_logging()  # идемпотентно: для запуска uvicorn напрямую
    _warn_if_multiple_workers()  # Э20.5: «Мультиплеер» ломается тихо при --workers > 1
    wire_default_ports()  # A-10: порты доменов ← реализации platform (идемпотентно)
    # L-07: общий keep-alive HTTP-клиент к OpenRouter (закрытие в finally).
    await init_http_client()
    pool = None
    log_sink: PgLogSink | None = None
    try:
        pool = await init_pool()
        sink = PostgresUsageSink(pool)
        await sink.warmup()
        set_default_usage_sink(sink)
        event(logger, "БД", "cost-учёт переключён на Postgres")
    except Exception as exc:
        event(
            logger,
            "БД",
            "Postgres недоступен: %s. Cost-учёт остаётся на JSONL",
            exc,
            level=logging.WARNING,
        )

    # Ключ OpenRouter из «Параметры» (account_settings владельца) → in-process holder ядра.
    if pool is not None:
        try:
            from core.platform.repo.accounts import resolve_default_account_id

            owner_account_id = await resolve_default_account_id()
            await load_openrouter_key_into_runtime(account_id=owner_account_id)
        except Exception as exc:
            event(
                logger,
                "БД",
                "ключ OpenRouter из БД не загружен: %s",
                exc,
                level=logging.WARNING,
            )
        else:
            # Этап 4 (план §6): резюме владельца — из resumes в holder (разовый импорт файла,
            # если строки ещё нет). Тот же account_id, что уже резолвили для ключа OpenRouter.
            try:
                await load_resume_into_runtime(account_id=owner_account_id)
            except Exception as exc:
                event(
                    logger,
                    "БД",
                    "резюме из БД не загружено: %s",
                    exc,
                    level=logging.WARNING,
                )

    # L-08: TCP+TLS к OpenRouter до первого пользовательского LLM-вызова.
    # После загрузки ключа из БД — тот же auth-путь, что у чата/скоринга.
    with suppress(Exception):
        await warmup_openrouter()

    spool_path = Path(get_core_settings().log_dir) / "_pg_spool.jsonl"
    log_sink = PgLogSink(pool, spool_path=spool_path)
    log_sink.start()
    set_default_log_sink(log_sink)
    if pool is not None:
        event(logger, "БД", "витрина логов готова (copilot_logs)")
    else:
        event(logger, "БД", "витрина логов в spool-режиме: PG недоступен", level=logging.WARNING)

    # A-20: единая очередь фоновых задач (salary_estimate, дайджест/прогрев из бота).
    try:
        await start_background_runtime(pool)
    except Exception as exc:  # noqa: BLE001 — API должен подняться даже если воркер не стартовал
        event(
            logger,
            "ОШИБКА",
            "очередь фоновых задач не стартовала: %s",
            exc,
            level=logging.ERROR,
            exc_info=True,
        )

    try:
        yield
    finally:
        with suppress(Exception):
            await stop_background_runtime()
        if log_sink is not None:
            await log_sink.stop()
            set_default_log_sink(None)
        set_default_usage_sink(None)
        if pool is not None:
            await close_pool()
        with suppress(Exception):
            await close_http_client()


# Версия = git sha сборки (COPILOT_GIT_SHA, deploy/Dockerfile), локально/без сборочного
# аргумента — фолбэк на прежний плейсхолдер.
app = FastAPI(
    title=get_settings().app_name,
    version=os.getenv("COPILOT_GIT_SHA") or "0.2.0",
    lifespan=lifespan,
)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_settings.frontend_origin],
    allow_origin_regex=_settings.extension_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # L-01: фронт/DevTools читают разбивку latency и корреляционный id.
    expose_headers=[REQUEST_ID_HEADER, SERVER_TIMING_HEADER],
)


@app.middleware("http")
async def account_llm_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Этап 5 fix (LLM key routing gap, see project_openrouter_key_flow_2026_08_05 в памяти):
    без этого middleware `get_chat_model` видел один ключ OpenRouter на весь процесс
    (`core.platform.config.runtime`), независимо от того, чей это запрос — заявка друга на
    свой ключ сохранялась бы в БД, но реально не использовалась.

    Раскрывает личность запроса ТЕМ ЖЕ кодом, что `require_account` (`resolve_request_account`
    — уже кэширован на 15 с, `api.security._load_cached`), и выставляет per-request
    `account_id` в `core.platform.config.runtime` контекстную переменную — читается синхронно
    из `get_chat_model` внутри обработчика (в т.ч. во время SSE-стрима: эмпирически проверено,
    что contextvar, выставленная здесь до `call_next()`, корректно долетает до тела
    `StreamingResponse`-генератора у Starlette/anyio — `call_next` копирует контекст в момент
    спауна внутренней task, не по ссылке, так что `finally`-сброс ниже не гонится с ещё не
    отданными чанками параллельного запроса).

    Middleware, не FastAPI-зависимость: `require_account`/`require_account_context` — обычные
    `async def` (не generator), их напрямую `await`-ят и в проде (`Depends`), и в тестах
    (`tests/test_auth_perimeter.py::_authed`) — превращать их в yield-зависимости ради этого
    сломало бы оба пути. Middleware оборачивает КАЖДЫЙ запрос без правки 20+ роутеров.
    """
    account, _authed = await resolve_request_account(
        request.headers.get("x-api-key"),
        request.headers.get("x-auth-token"),
        request.cookies.get(AUTH_COOKIE),
        x_extension_version=request.headers.get("x-extension-version"),
    )
    token = None
    if account is not None:
        try:
            await prime_runtime_openrouter_key_for_account(account.account_id)
        except Exception as exc:  # noqa: BLE001 — недоступный PG не должен ронять запрос
            logger.debug("account_llm_context: prime не удался: %s", exc)
        try:
            await touch_account_last_seen(account.account_id, client_ip(request))
        except Exception as exc:  # noqa: BLE001 — телеметрия не должна ронять запрос
            logger.debug("account_llm_context: touch_account_last_seen не удался: %s", exc)
        token = set_current_account_id(account.account_id)
    try:
        return await call_next(request)
    finally:
        if token is not None:
            reset_current_account_id(token)


_HTTP_LOG_SKIP_PREFIXES = ("/health", "/api/logs")

# Методы, меняющие состояние: их пишем в витрину (INFO) — из них складывается лента
# «что человек делал», которую читает разработчик в бандле логов. Успешные GET-ы туда не
# идут: фронт опрашивает их по таймеру, они утопили бы всё остальное.
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Мутации-heartbeat'ы: тик-репорты раннеров расширения бьют каждый тик (5 мин / 1 мин) по
# каждому аккаунту — как GET-поллинг, утопили бы витрину. Успешные (2xx) → DEBUG; 4xx/5xx
# по-прежнему WARNING/ERROR (отвалившаяся heartbeat-ручка — это как раз то, что надо видеть).
# Сам сигнал «раннер жив / раннер бьётся» несёт доменное событие (АВТООТКЛИК/АВТОПРОСМОТР
# «тик: …»), троттлится на стороне сценария.
_QUIET_MUTATION_PATHS = frozenset(
    {
        "/api/pipeline/auto-apply/tick-report",
        "/api/opportunities/discovery/tick-report",
    }
)

# Успешный, но подозрительно долгий запрос тоже попадает в витрину: без этого «всё грузится
# вечно» не с чем сопоставить.
_SLOW_REQUEST_MS = 3_000.0

# L-01: Server-Timing + X-Request-Id на каждом ответе (в т.ч. /health).
app.middleware("http")(request_timing_middleware)


def _http_log_level(*, method: str, status: int, duration_ms: float, path: str = "") -> int:
    """Уровень строки HTTP-лога.

    Порог витрины логов (`QueueLogHandler`) — INFO, поэтому DEBUG виден только в файле на
    сервере. Отсюда правило: всё, что нужно в бандле пользователя, обязано быть INFO+.
    5xx → ERROR, 4xx → WARNING (отказ пользователю: 401/404/422 объясняют «кнопка не сработала»),
    мутация или медленный ответ → INFO, остальное (фон/поллинг) → DEBUG.
    """
    if status >= 500:
        return logging.ERROR
    if status >= 400:
        return logging.WARNING
    if status < 400 and path in _QUIET_MUTATION_PATHS:
        return logging.DEBUG
    if method in _MUTATING_METHODS or duration_ms >= _SLOW_REQUEST_MS:
        return logging.INFO
    return logging.DEBUG


@app.middleware("http")
async def http_logging_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    path = request.url.path
    if path.startswith(_HTTP_LOG_SKIP_PREFIXES):
        return await call_next(request)

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        event(
            logger,
            "ОШИБКА",
            "%s %s -> исключение за %.0f мс",
            request.method,
            path,
            duration_ms,
            level=logging.ERROR,
            method=request.method,
            path=path,
            duration_ms=round(duration_ms),
            request_id=getattr(request.state, "request_id", None) or "-",
        )
        raise

    duration_ms = (time.perf_counter() - start) * 1000
    status = response.status_code
    level = _http_log_level(
        method=request.method, status=status, duration_ms=duration_ms, path=path
    )
    # Поля, а не только текст: по ним фильтруется витрина и строится статистика в бандле.
    event(
        logger,
        "ОШИБКА" if level >= logging.ERROR else "HTTP",
        "%s %s -> %d за %.0f мс",
        request.method,
        path,
        status,
        duration_ms,
        level=level,
        method=request.method,
        path=path,
        status=status,
        duration_ms=round(duration_ms),
        request_id=getattr(request.state, "request_id", None) or "-",
        slow=duration_ms >= _SLOW_REQUEST_MS,
    )
    return response


@app.exception_handler(DomainError)
async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    """Любой непроброшенный через to_http DomainError → единый конверт + статус."""
    response = to_response(exc)
    event(
        logger,
        "ОШИБКА",
        "%s %s -> %s: %s",
        request.method,
        request.url.path,
        exc.code,
        exc.message,
        # Доменная ошибка — это отказ по бизнес-правилу (нет ключа, пустой вход), а не поломка
        # сервиса: 5xx пишем как ERROR, 4xx как WARNING, иначе errors.txt тонет в штатных отказах.
        level=logging.ERROR if response.status_code >= 500 else logging.WARNING,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        code=exc.code,
        request_id=getattr(request.state, "request_id", None) or "-",
    )
    return response


@app.exception_handler(Exception)
async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Гарантирует, что трейсбек любого необработанного исключения осядет в
    errors.log/copilot_logs, а не только в stdout окна процесса."""
    event(
        logger,
        "ОШИБКА",
        "%s %s -> необработанное исключение: %s",
        request.method,
        request.url.path,
        exc,
        level=logging.ERROR,
        exc_info=True,
        method=request.method,
        path=request.url.path,
        status=500,
        error_type=type(exc).__name__,
        request_id=getattr(request.state, "request_id", None) or "-",
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# Публичные: /health, /auth/*. За require_account (web-токен ИЛИ X-API-Key): /api/*, /score.
mount_routers(app, require_account=require_account)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
