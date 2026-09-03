"""Тайминги текущего HTTP-запроса: db / llm / app → `Server-Timing`.

Наполняется из пула Postgres и `platform.llm.call`; читается middleware в `api.main`.
Вне HTTP-запроса (бот, CLI, тесты) `record_*` — no-op.
"""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


@dataclass(slots=True)
class RequestTiming:
    """Накопитель длительностей внутри одного запроса."""

    request_id: str
    db_ms: float = 0.0
    llm_ms: float = 0.0
    started: float = field(default_factory=time.perf_counter)

    def add_db(self, ms: float) -> None:
        if ms > 0:
            self.db_ms += ms

    def add_llm(self, ms: float) -> None:
        if ms > 0:
            self.llm_ms += ms

    def server_timing_header(self, total_ms: float | None = None) -> str:
        """W3C Server-Timing: `db`, `llm`, `app`, `total` (мс, 1 знак)."""
        wall = total_ms if total_ms is not None else (time.perf_counter() - self.started) * 1000
        db = self.db_ms
        llm = self.llm_ms
        app = max(0.0, wall - db - llm)
        return f"db;dur={db:.1f}, llm;dur={llm:.1f}, app;dur={app:.1f}, total;dur={wall:.1f}"


_timing_var: ContextVar[RequestTiming | None] = ContextVar("request_timing", default=None)


def begin_request(
    request_id: str | None = None,
) -> tuple[RequestTiming, Token[RequestTiming | None]]:
    """Открыть контекст запроса; вернуть (timing, token для reset)."""
    timing = RequestTiming(request_id=request_id or str(uuid.uuid4()))
    token = _timing_var.set(timing)
    return timing, token


def end_request(token: Token[RequestTiming | None]) -> None:
    _timing_var.reset(token)


def current_timing() -> RequestTiming | None:
    return _timing_var.get()


def record_db_ms(ms: float) -> None:
    timing = _timing_var.get()
    if timing is not None:
        timing.add_db(ms)


def record_llm_ms(ms: float) -> None:
    timing = _timing_var.get()
    if timing is not None:
        timing.add_llm(ms)


__all__ = [
    "RequestTiming",
    "begin_request",
    "current_timing",
    "end_request",
    "record_db_ms",
    "record_llm_ms",
]
