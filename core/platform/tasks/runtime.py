"""Рантайм очереди: enqueue, воркер, ежедневный cron-тикер.

`platform` не знает про дайджест/зарплату — только kind → handler. Обработчики
регистрирует `core.app.background` и `bot_app` на старте.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from core.platform.observability import event
from core.platform.tasks.models import CronSpec, TaskRecord
from core.platform.tasks.store import MemoryTaskStore, TaskStore

logger = logging.getLogger(__name__)

Handler = Callable[[Mapping[str, Any]], Awaitable[None]]

# Композиционный корень (core/app/background.py) внедряет пару enter/exit — платформа не знает
# про ContextVar аккаунта/приоритет ключа OpenRouter (core.config), только зовёт хук вокруг
# исполнения account-задачи (plans/multitenancy_gaps_2026_08_06.md §3.10). enter возвращает
# непрозрачный токен, который exit обязан получить обратно — тот же паттерн, что
# core.config.set_current_account_id/reset_current_account_id.
AccountContextEnter = Callable[[int], Awaitable[Any]]
AccountContextExit = Callable[[Any], Awaitable[None]]

_DEFAULT_POLL_SEC = 1.0
_DEFAULT_CRON_TICK_SEC = 15.0
_BACKOFF_BASE_SEC = 5.0
_BACKOFF_CAP_SEC = 300.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _local_now() -> datetime:
    """Локальное время хоста — как у прежнего APScheduler (tzlocal)."""
    return datetime.now().astimezone()


class TaskRuntime:
    """Единый планировщик: очередь с приоритетами + ежедневные cron → enqueue."""

    def __init__(self, store: TaskStore | None = None) -> None:
        self._store: TaskStore = store or MemoryTaskStore()
        self._handlers: dict[str, Handler] = {}
        self._crons: dict[str, CronSpec] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._cron_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._poll_sec = _DEFAULT_POLL_SEC
        self._cron_tick_sec = _DEFAULT_CRON_TICK_SEC
        self._account_enter: AccountContextEnter | None = None
        self._account_exit: AccountContextExit | None = None

    @property
    def store(self) -> TaskStore:
        return self._store

    def set_store(self, store: TaskStore) -> None:
        self._store = store

    def register_handler(self, kind: str, handler: Handler) -> None:
        key = (kind or "").strip()
        if not key:
            raise ValueError("kind обработчика пуст")
        self._handlers[key] = handler

    def add_cron(self, spec: CronSpec) -> None:
        self._crons[spec.schedule_id] = spec

    def set_account_context(self, enter: AccountContextEnter, exit_: AccountContextExit) -> None:
        """Внедрить hook, которым `_execute` оборачивает вызов handler'а account-задачи."""
        self._account_enter = enter
        self._account_exit = exit_

    def remove_cron(self, schedule_id: str) -> None:
        self._crons.pop(schedule_id, None)

    async def enqueue(
        self,
        kind: str,
        *,
        payload: Mapping[str, Any] | None = None,
        priority: int = 100,
        idempotency_key: str | None = None,
        run_at: datetime | None = None,
        max_attempts: int = 3,
        account_id: int | None = None,
    ) -> TaskRecord:
        key = (kind or "").strip()
        if not key:
            raise ValueError("kind задачи пуст")
        when = run_at or _utcnow()
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        task = await self._store.enqueue(
            kind=key,
            payload=dict(payload or {}),
            priority=priority,
            idempotency_key=idempotency_key,
            run_at=when,
            max_attempts=max(1, max_attempts),
            account_id=account_id,
        )
        event(
            logger,
            "ЗАДАЧА",
            "в очереди kind=%s id=%s prio=%s key=%s",
            key,
            task.id,
            priority,
            idempotency_key or "-",
            task_id=str(task.id),
            kind=key,
        )
        return task

    def enqueue_soon(
        self,
        kind: str,
        *,
        payload: Mapping[str, Any] | None = None,
        priority: int = 100,
        idempotency_key: str | None = None,
        run_at: datetime | None = None,
        max_attempts: int = 3,
        account_id: int | None = None,
    ) -> None:
        """Синхронный мост: положить enqueue в текущий loop (без ожидания)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            event(
                logger,
                "ЗАДАЧА",
                "enqueue_soon без loop: kind=%s пропущен",
                kind,
                level=logging.WARNING,
                kind=kind,
            )
            return

        async def _run() -> None:
            try:
                await self.enqueue(
                    kind,
                    payload=payload,
                    priority=priority,
                    idempotency_key=idempotency_key,
                    run_at=run_at,
                    max_attempts=max_attempts,
                    account_id=account_id,
                )
            except Exception as exc:  # noqa: BLE001 — фон не валит вызывающего
                # Гонка на идемпотентном ключе — не сбой: параллельный вызывающий уже поставил
                # ту же задачу, уникальный индекс `background_tasks_idempotency_active_uidx`
                # ровно для этого и заведён. В журнале это стояло ERROR'ом и выглядело как
                # поломка очереди (прод, 6 строк за сутки на `rescore_weights_version`).
                duplicate = "idempotency" in str(exc) and "duplicate key" in str(exc)
                event(
                    logger,
                    "ЗАДАЧА" if duplicate else "ОШИБКА",
                    (
                        "enqueue kind=%s: задача с тем же идемпотентным ключом уже в очереди"
                        if duplicate
                        else "enqueue failed kind=%s: %s"
                    ),
                    kind,
                    *(() if duplicate else (exc,)),
                    level=logging.INFO if duplicate else logging.ERROR,
                    exc_info=not duplicate,
                    kind=kind,
                )

        loop.create_task(_run(), name=f"tasks.enqueue:{kind}")

    async def list_recent(
        self, *, limit: int = 50, account_id: int | None = None
    ) -> list[TaskRecord]:
        return await self._store.list_recent(limit=limit, account_id=account_id)

    async def has_active(self, idempotency_key: str) -> bool:
        return await self._store.has_active(idempotency_key)

    async def reclaim_stuck(self) -> int:
        n = await self._store.reclaim_stuck()
        if n:
            event(logger, "ЗАДАЧА", "восстановлено зависших задач: %s", n)
        return n

    async def retry_task(self, task_id: int) -> TaskRecord | None:
        """Вернуть упавшую/отменённую в pending со сброшенными attempts. None — нельзя."""
        return await self._store.retry_task(task_id)

    async def cancel_task(self, task_id: int) -> TaskRecord | None:
        """Снять pending/running. done и failed не трогает. None — нельзя."""
        return await self._store.cancel_task(task_id)

    async def retry_failed_of_kind(self, kind: str, *, reason: str = "") -> int:
        """Перезапустить упавшие этого kind (опционально одной причины)."""
        return await self._store.retry_failed_of_kind(kind, reason=reason)

    async def cancel_failed_of_kind(self, kind: str, *, reason: str = "") -> int:
        """Снять упавшие этого kind (опционально одной причины) — retry не поможет."""
        return await self._store.cancel_failed_of_kind(kind, reason=reason)

    @property
    def running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    async def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        await self.reclaim_stuck()
        self._worker_task = asyncio.create_task(self._worker_loop(), name="tasks.worker")
        self._cron_task = asyncio.create_task(self._cron_loop(), name="tasks.cron")
        event(
            logger,
            "ЗАПУСК",
            "очередь фоновых задач: воркер + cron (%s расписаний)",
            len(self._crons),
        )

    async def stop(self) -> None:
        self._stop.set()
        for task in (self._worker_task, self._cron_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._worker_task = None
        self._cron_task = None
        event(logger, "ЗАПУСК", "очередь фоновых задач остановлена")

    async def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                claimed = await self._store.claim_next(kinds=tuple(self._handlers))
            except Exception as exc:  # noqa: BLE001
                event(
                    logger,
                    "ОШИБКА",
                    "claim_next: %s",
                    exc,
                    level=logging.ERROR,
                    exc_info=True,
                )
                await asyncio.sleep(self._poll_sec)
                continue
            if claimed is None:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=self._poll_sec)
                continue
            await self._execute(claimed)

    def _backoff_sec(self, attempts: int) -> float:
        return min(_BACKOFF_CAP_SEC, _BACKOFF_BASE_SEC * (2 ** max(0, attempts - 1)))

    async def _execute(self, task: TaskRecord) -> None:
        handler = self._handlers.get(task.kind)
        if handler is None:
            await self._store.mark_retry_or_fail(
                task.id,
                error=f"нет обработчика kind={task.kind!r}",
                backoff_sec=self._backoff_sec(task.attempts),
            )
            event(
                logger,
                "ОШИБКА",
                "задача id=%s: нет handler для %s",
                task.id,
                task.kind,
                level=logging.ERROR,
                task_id=str(task.id),
                kind=task.kind,
            )
            return
        ctx_token: Any = None
        if task.account_id is not None and self._account_enter is not None:
            try:
                ctx_token = await self._account_enter(task.account_id)
            except Exception as exc:  # noqa: BLE001 — сбой прайминга не должен ронять задачу
                event(
                    logger,
                    "ОШИБКА",
                    "задача id=%s: account-context enter упал: %s",
                    task.id,
                    exc,
                    level=logging.ERROR,
                    task_id=str(task.id),
                    kind=task.kind,
                )
        try:
            try:
                await handler(task.payload)
            except Exception as exc:  # noqa: BLE001 — ретраи на уровне очереди
                status = await self._store.mark_retry_or_fail(
                    task.id,
                    error=str(exc),
                    backoff_sec=self._backoff_sec(task.attempts),
                )
                event(
                    logger,
                    "ОШИБКА",
                    "задача id=%s kind=%s attempt=%s → %s: %s",
                    task.id,
                    task.kind,
                    task.attempts,
                    status,
                    exc,
                    level=logging.ERROR,
                    exc_info=True,
                    task_id=str(task.id),
                    kind=task.kind,
                )
                return
            await self._store.mark_done(task.id)
            event(
                logger,
                "ЗАДАЧА",
                "готово id=%s kind=%s",
                task.id,
                task.kind,
                task_id=str(task.id),
                kind=task.kind,
            )
        finally:
            if ctx_token is not None and self._account_exit is not None:
                try:
                    await self._account_exit(ctx_token)
                except Exception as exc:  # noqa: BLE001 — сброс контекста не должен ронять воркер
                    event(
                        logger,
                        "ОШИБКА",
                        "задача id=%s: account-context exit упал: %s",
                        task.id,
                        exc,
                        level=logging.ERROR,
                        task_id=str(task.id),
                        kind=task.kind,
                    )

    async def _cron_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick_crons()
            except Exception as exc:  # noqa: BLE001
                event(
                    logger,
                    "ОШИБКА",
                    "cron tick: %s",
                    exc,
                    level=logging.ERROR,
                    exc_info=True,
                )
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._cron_tick_sec)

    async def _tick_crons(self) -> None:
        if not self._crons:
            return
        now_local = _local_now()
        today = now_local.date()
        for spec in list(self._crons.values()):
            if not spec.enabled:
                continue
            if not (0 <= spec.hour <= 23 and 0 <= spec.minute <= 59):
                continue
            scheduled = now_local.replace(
                hour=spec.hour, minute=spec.minute, second=0, microsecond=0
            )
            delta = (now_local - scheduled).total_seconds()
            # Ещё не наступило; или опоздание больше grace (как misfire APScheduler).
            if delta < 0 or delta > spec.misfire_grace_sec:
                continue
            idem = f"{spec.schedule_id}:{today.isoformat()}"
            if await self._store.exists_key(idem):
                continue
            await self.enqueue(
                spec.kind,
                payload=spec.payload,
                priority=spec.priority,
                idempotency_key=idem,
                run_at=_utcnow(),
            )


_RUNTIME: TaskRuntime | None = None


def get_runtime() -> TaskRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = TaskRuntime()
    return _RUNTIME


def reset_runtime_for_tests(store: TaskStore | None = None) -> TaskRuntime:
    """Сбросить синглтон (только тесты)."""
    global _RUNTIME
    _RUNTIME = TaskRuntime(store=store or MemoryTaskStore())
    return _RUNTIME


async def enqueue(
    kind: str,
    *,
    payload: Mapping[str, Any] | None = None,
    priority: int = 100,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3,
    account_id: int | None = None,
) -> TaskRecord:
    return await get_runtime().enqueue(
        kind,
        payload=payload,
        priority=priority,
        idempotency_key=idempotency_key,
        run_at=run_at,
        max_attempts=max_attempts,
        account_id=account_id,
    )


def enqueue_soon(
    kind: str,
    *,
    payload: Mapping[str, Any] | None = None,
    priority: int = 100,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3,
    account_id: int | None = None,
) -> None:
    get_runtime().enqueue_soon(
        kind,
        payload=payload,
        priority=priority,
        idempotency_key=idempotency_key,
        run_at=run_at,
        max_attempts=max_attempts,
        account_id=account_id,
    )


def register_handler(kind: str, handler: Handler) -> None:
    get_runtime().register_handler(kind, handler)


def add_cron(spec: CronSpec) -> None:
    get_runtime().add_cron(spec)


__all__ = [
    "Handler",
    "TaskRuntime",
    "add_cron",
    "enqueue",
    "enqueue_soon",
    "get_runtime",
    "register_handler",
    "reset_runtime_for_tests",
]
