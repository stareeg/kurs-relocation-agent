"""Витрина логов в Postgres + spool-буфер.

Поток INFO+ оседает в таблице `copilot_logs` для интерфейса. Запись неблокирующая:
`QueueLogHandler` в `emit` только кладёт сериализованную запись в очередь (без сети, без
ожидания event loop), фоновый `PgLogSink` дренит её и пишет пачками (`executemany`).

Пока PG не поднят или лежит — строки уходят в spool-файл `logs/_pg_spool.jsonl`; при
восстановлении PG писатель сначала дозаливает spool, затем пишет текущий батч. Так
логирование никогда не ждёт сеть и не валится из-за БД.

FR2-69: spool ограничен сверху (~20 МБ, старые строки отбрасываются с одной WARNING);
replay читает файл чанками, не целиком в память. Все дисковые операции (spool-запись,
подрезка, чтение, restore) вынесены в `asyncio.to_thread` — даже 20-МБ trim не блокирует
event loop API-процесса.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.platform.observability.logging import record_to_dict

logger = logging.getLogger(__name__)

# Очередь между хендлером (emit) и фоновым писателем. Ограничена сверху: если писателя нет
# (CLI/standalone-бот без витрины) — лишнее тихо отбрасывается, без утечки памяти.
_MAX_QUEUE = 10_000
_log_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_MAX_QUEUE)

_INSERT_SQL = (
    "insert into copilot_logs (ts, level, logger, event, task_id, msg, fields, account_id) "
    "values ($1, $2, $3, $4, $5, $6, $7, $8)"
)

# FR2-69: потолок spool на диске (байты). Свыше — оставляем хвост, головы режем.
DEFAULT_SPOOL_MAX_BYTES = 20 * 1024 * 1024

# Глобальный писатель (параллель с set_default_usage_sink): lifespan регистрирует, тесты читают.
_log_sink: PgLogSink | None = None


def set_default_log_sink(sink: PgLogSink | None) -> None:
    """Зарегистрировать фоновый писатель витрины (None — снять при остановке)."""
    global _log_sink
    _log_sink = sink


def get_default_log_sink() -> PgLogSink | None:
    return _log_sink


class QueueLogHandler(logging.Handler):
    """Хендлер уровня INFO: в emit только кладёт запись в очередь — без сети и блокировок.

    Навешивается в `setup_logging` (L1) на root, но реальным потребителем очереди становится
    `PgLogSink`, который поднимается в lifespan API после пула.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _log_queue.put_nowait(record_to_dict(record))
        except queue.Full:
            pass  # писатель не успевает/не запущен — строка витрины теряется, файл и консоль целы
        except Exception:  # noqa: BLE001 — логирование не должно ронять прикладной код
            self.handleError(record)


def _to_dt(ts: Any) -> datetime:
    """ISO-строка ts (из record_to_dict / spool) → datetime для timestamptz-параметра asyncpg."""
    if isinstance(ts, datetime):
        return ts
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts)
        except ValueError:
            pass
    return datetime.now(tz=UTC)


def trim_spool_bytes(data: bytes, max_bytes: int) -> bytes:
    """Оставить хвост ≤ max_bytes, выровненный по границе строки (для тестов)."""
    if max_bytes <= 0:
        return b""
    if len(data) <= max_bytes:
        return data
    return _align_tail_to_line(data[-max_bytes:])


def _align_tail_to_line(tail: bytes) -> bytes:
    """Сбросить неполную первую строку в окне хвоста."""
    nl = tail.find(b"\n")
    if nl == -1:
        # Нет полной строки в окне — лучше пустой spool, чем битый JSON.
        return b""
    return tail[nl + 1 :]


class PgLogSink:
    """Фоновый писатель витрины: дренит очередь, пишет пачками в copilot_logs, при сбое БД
    складывает в spool и дозаливает позже. Поднимается в lifespan API рядом с пулом."""

    def __init__(
        self,
        pool: Any | None,
        *,
        spool_path: str | Path,
        batch_size: int = 200,
        flush_interval: float = 1.0,
        spool_max_bytes: int = DEFAULT_SPOOL_MAX_BYTES,
    ) -> None:
        self._pool = pool
        self._spool = Path(spool_path)
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._spool_max_bytes = spool_max_bytes
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._degraded = False  # БД лежит — гасим повторные WARNING до восстановления
        self._spool_cap_warned = False  # одна WARNING на эпизод переполнения spool

    def start(self) -> None:
        """Запустить фоновый дренаж (идемпотентно)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Дать писателю финально слить очередь и остановиться."""
        self._stopping = True
        if self._task is not None:
            try:
                await self._task
            except Exception as exc:  # noqa: BLE001
                logger.warning("PgLogSink: писатель завершился с ошибкой: %s", exc)
            self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            await self._tick()
            try:
                await asyncio.sleep(self._flush_interval)
            except asyncio.CancelledError:
                break
        await self._tick()  # финальный слив очереди на остановке

    async def _tick(self) -> None:
        await self._replay_spool()
        batch = self._drain_queue()
        if batch:
            await self._write(batch)

    def _drain_queue(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while len(batch) < self._batch_size:
            try:
                batch.append(_log_queue.get_nowait())
            except queue.Empty:
                break
        return batch

    async def _write(self, rows: list[dict[str, Any]]) -> None:
        if self._pool is None:
            await asyncio.to_thread(self._spool_rows, rows)
            return
        try:
            await self._insert(rows)
        except Exception as exc:  # noqa: BLE001 — БД лежит/упала: в spool, повтор на след. тике
            self._note_degraded(exc)
            await asyncio.to_thread(self._spool_rows, rows)
            return
        self._note_recovered()

    async def _insert(self, rows: list[dict[str, Any]]) -> None:
        pool = self._pool
        if pool is None:
            return
        args = [
            (
                _to_dt(r.get("ts")),
                r.get("level") or "INFO",
                r.get("logger"),
                r.get("event"),
                r.get("task_id"),
                r.get("msg") or "",
                r.get("fields"),
                r.get("account_id"),
            )
            for r in rows
        ]
        await pool.executemany(_INSERT_SQL, args)

    def _spool_rows(self, rows: list[dict[str, Any]]) -> None:
        try:
            self._spool.parent.mkdir(parents=True, exist_ok=True)
            with self._spool.open("a", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            self._enforce_spool_cap()
        except OSError as exc:
            logger.warning("PgLogSink: spool-запись не удалась: %s", exc)

    def _enforce_spool_cap(self) -> None:
        """Если spool > лимита — оставить хвост, старые строки выкинуть.

        Читаем только окно с конца файла (не весь spool в RAM).
        """
        try:
            size = self._spool.stat().st_size
        except OSError:
            return
        if size <= self._spool_max_bytes:
            return
        try:
            with self._spool.open("rb") as fh:
                fh.seek(max(0, size - self._spool_max_bytes))
                tail = fh.read()
            trimmed = _align_tail_to_line(tail)
            self._spool.write_bytes(trimmed)
        except OSError as exc:
            logger.warning("PgLogSink: не удалось подрезать spool: %s", exc)
            return
        # Одна WARNING на эпизод переполнения (пока PG не ожил — без спама на каждый trim).
        if not self._spool_cap_warned:
            self._spool_cap_warned = True
            mb = self._spool_max_bytes / (1024 * 1024)
            logger.warning(
                "PgLogSink: spool превысил %.0f МБ, старые строки отброшены (оставлен хвост)",
                mb,
            )

    def _replaying_path(self) -> Path:
        return self._spool.with_name(self._spool.name + ".replaying")

    async def _replay_spool(self) -> None:
        """Дозалить spool в таблицу чанками (не целиком в RAM) и очистить (каждый тик)."""
        if self._pool is None:
            return

        replaying = self._replaying_path()
        # Дозалить недоигранный .replaying после краша, иначе взять текущий spool.
        prepared = await asyncio.to_thread(self._prepare_replay_file, replaying)
        if not prepared:
            return

        total = 0
        restore_chunk: list[dict[str, Any]] | None = None
        restore_rest = ""
        try:
            with replaying.open("r", encoding="utf-8") as fh:
                while True:
                    chunk = await asyncio.to_thread(self._read_spool_chunk, fh)
                    if not chunk:
                        break
                    try:
                        await self._insert(chunk)
                    except Exception as exc:  # noqa: BLE001 — PG ещё лежит
                        self._note_degraded(exc)
                        # Сначала дочитать хвост; unlink — после закрытия fh (WinError 32).
                        restore_chunk = chunk
                        restore_rest = await asyncio.to_thread(fh.read)
                        break
                    total += len(chunk)
        except OSError as exc:
            logger.warning("PgLogSink: spool не прочитан: %s", exc)
            return

        if restore_chunk is not None:
            await asyncio.to_thread(self._restore_failed_replay, restore_chunk, restore_rest)
            return

        await asyncio.to_thread(self._finalize_replay, replaying, total)

    def _read_spool_chunk(self, fh: Any) -> list[dict[str, Any]]:
        """Прочитать до batch_size валидных JSON-строк из уже открытого файла."""
        chunk: list[dict[str, Any]] = []
        while len(chunk) < self._batch_size:
            line = fh.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                chunk.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return chunk

    def _prepare_replay_file(self, replaying: Path) -> bool:
        """Подготовить .replaying-файл к дозаливу (sync I/O — вызывать через to_thread).

        True — файл готов к чтению; False — дозаливать нечего (spool пуст/отсутствует).
        """
        if not replaying.exists():
            if not self._spool.exists():
                return False
            try:
                if self._spool.stat().st_size == 0:
                    self._spool.unlink(missing_ok=True)
                    return False
                self._spool.replace(replaying)
            except OSError as exc:
                logger.warning("PgLogSink: spool не прочитан: %s", exc)
                return False
        return True

    def _finalize_replay(self, replaying: Path, total: int) -> None:
        """Удалить .replaying после успешного дозалива и залогировать результат (sync I/O)."""
        try:
            replaying.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("PgLogSink: не удалось удалить .replaying: %s", exc)
        if total:
            self._note_recovered()
            logger.info("PgLogSink: spool дозалит в copilot_logs (%d строк)", total)

    def _restore_failed_replay(self, failed_chunk: list[dict[str, Any]], rest: str) -> None:
        """Вернуть неудавшийся чанк + непрочитанный хвост в spool; убрать .replaying."""
        replaying = self._replaying_path()
        try:
            self._spool.parent.mkdir(parents=True, exist_ok=True)
            with self._spool.open("w", encoding="utf-8") as out:
                for r in failed_chunk:
                    out.write(json.dumps(r, ensure_ascii=False) + "\n")
                if rest:
                    out.write(rest)
            replaying.unlink(missing_ok=True)
            self._enforce_spool_cap()
        except OSError as exc:
            logger.warning("PgLogSink: не удалось вернуть spool после сбоя replay: %s", exc)

    def _note_degraded(self, exc: Exception) -> None:
        """Первый сбой записи — одна WARNING; дальнейшие до восстановления — DEBUG (без спама)."""
        if not self._degraded:
            self._degraded = True
            logger.warning("PgLogSink: БД недоступна, витрина пишется в spool: %s", exc)
        else:
            logger.debug("PgLogSink: запись отложена в spool: %s", exc)

    def _note_recovered(self) -> None:
        if self._degraded:
            self._degraded = False
            logger.info("PgLogSink: БД снова доступна, витрина пишется в copilot_logs")
        # После восстановления можно снова предупредить, если spool опять раздуется.
        self._spool_cap_warned = False
