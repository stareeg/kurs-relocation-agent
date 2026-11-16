"""Запуски агента: старт фоновой задачи, статус, SSE-поток событий, подтверждение (A-3).

Старт сразу отвечает 202 со статусом `queued` — задача живёт в процессе API после
отключения клиента. События отдаются единым SSE-контрактом (`api/streaming`): догон по
`Last-Event-ID`/`after`, затем живая очередь запуска (или полл базы, если задача не в
этом процессе — например после рестарта API во время паузы). Поток закрывается
терминальным событием (`done`/`failed`).

Подтверждение («да»/«нет») снимает паузу графа: живой запуск получает решение через
очередь, запуск после рестарта — резюмится с чекпойнта Postgres.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.errors import to_http
from api.schemas import (
    AgentApprovalIn,
    AgentEventList,
    AgentEventOut,
    AgentRunCreate,
    AgentRunList,
    AgentRunOut,
    AgentSettingsIn,
    AgentSettingsOut,
)
from api.security import AccountContext, require_account_context
from core.app.agent.runs import TERMINAL_EVENT_TYPES, get_runs_manager
from core.kernel.errors import DomainError
from core.platform.repo import agent_chats as chats_repo
from core.platform.repo import agent_runs as runs_repo
from core.platform.repo.settings import get_agent_confirm_mode, set_agent_confirm_mode

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent-runs"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_SSE_MEDIA_TYPE = "text/event-stream"
_HEARTBEAT_S = 15.0
_LIVE_POLL_S = 0.25
_DB_POLL_S = 1.5


def run_out(record: Any) -> AgentRunOut:
    """Строка запуска → контракт (без thread_id)."""
    return AgentRunOut(
        id=record.id,
        goal=record.goal,
        status=record.status,
        session_id=record.session_id,
        stop_reason=record.stop_reason,
        answer=record.answer,
        error=record.error,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def event_out(record: Any) -> AgentEventOut:
    """Строка события → контракт."""
    return AgentEventOut(
        id=record.id,
        type=record.type,
        payload=record.payload or {},
        node=record.node,
        duration_ms=record.duration_ms,
        created_at=record.created_at,
    )


def _sse_name(event_type: str) -> str:
    """Тип события → каноническое имя SSE: done/failed терминальные, остальное — progress."""
    if event_type == "done":
        return "done"
    if event_type == "failed":
        return "error"
    return "progress"


def _sse_frame(event_type: str, event_id: int, record: Any) -> bytes:
    payload = dict(record.payload or {})
    payload["type"] = record.type
    if record.duration_ms is not None:
        payload["duration_ms"] = record.duration_ms
    line = json.dumps(payload, ensure_ascii=False)
    name = _sse_name(event_type)
    return f"id: {event_id}\nevent: {name}\ndata: {line}\n\n".encode()


@router.post("/runs", response_model=AgentRunOut, status_code=202)
async def create_agent_run(
    body: AgentRunCreate, account: AccountContext = Depends(require_account_context)
) -> AgentRunOut:
    """Запустить агента фоновой задачей. 503 — нет чекпойнтера/БД; 404 — чужая сессия."""
    manager = get_runs_manager()
    if not manager.ready:
        raise HTTPException(status_code=503, detail="Агент недоступен: чекпойнтер не поднят")
    try:
        if body.session_id is not None:
            session = await chats_repo.get_session(body.session_id, account_id=account.account_id)
            if session is None:
                raise DomainError(f"Диалог {body.session_id} не найден", code="not_found")
        # Режим подтверждения (OQ-8) фиксируется на старте: переключатель меняет следующие запуски.
        mode = await get_agent_confirm_mode(account_id=account.account_id)
        record = await manager.start_run(
            account_id=account.account_id,
            goal=body.goal.strip(),
            session_id=body.session_id,
            auto_confirm=mode == "auto",
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return run_out(record)


@router.get("/runs", response_model=AgentRunList)
async def list_agent_runs(
    session_id: int | None = None,
    limit: int = 20,
    account: AccountContext = Depends(require_account_context),
) -> AgentRunList:
    """Запуски аккаунта (для восстановления экрана после перезагрузки страницы)."""
    try:
        records = await runs_repo.list_runs(
            account_id=account.account_id, session_id=session_id, limit=min(limit, 100)
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return AgentRunList(items=[run_out(r) for r in records])


@router.get("/runs/{run_id}", response_model=AgentRunOut)
async def get_agent_run(
    run_id: int, account: AccountContext = Depends(require_account_context)
) -> AgentRunOut:
    """Статус запуска (чужой запуск — 404)."""
    try:
        record = await runs_repo.get_run(run_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    return run_out(record)


@router.get("/runs/{run_id}/events/replay", response_model=AgentEventList)
async def replay_agent_run_events(
    run_id: int,
    after: int = 0,
    limit: int = 500,
    account: AccountContext = Depends(require_account_context),
) -> AgentEventList:
    """События запуска списком (JSON) — восстановление экрана без стрима."""
    try:
        record = await runs_repo.get_run(run_id, account_id=account.account_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Запуск не найден")
        events = await runs_repo.list_events(
            run_id=run_id, account_id=account.account_id, after_id=after, limit=min(limit, 1000)
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return AgentEventList(items=[event_out(e) for e in events])


@router.get("/runs/{run_id}/events")
async def stream_agent_run_events(
    run_id: int,
    request: Request,
    after: int = 0,
    account: AccountContext = Depends(require_account_context),
) -> StreamingResponse:
    """SSE-поток событий запуска: догон по `after`/Last-Event-ID, затем живое следование."""
    try:
        record = await runs_repo.get_run(run_id, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Запуск не найден")
    header = request.headers.get("last-event-id")
    cursor = after
    if header and header.isdigit() and int(header) > cursor:
        cursor = int(header)
    return StreamingResponse(
        _events_stream(run_id=run_id, account_id=account.account_id, cursor=cursor),
        media_type=_SSE_MEDIA_TYPE,
        headers=_SSE_HEADERS,
    )


async def _events_stream(*, run_id: int, account_id: int, cursor: int) -> AsyncIterator[bytes]:
    """Догон из базы → живая очередь запуска (или полл базы) → терминал закрывает поток."""
    manager = get_runs_manager()
    live_queue = manager.subscribe_live(run_id)
    last_yield = time.monotonic()
    try:
        while True:
            batch = await runs_repo.list_events(
                run_id=run_id, account_id=account_id, after_id=cursor
            )
            for event in batch:
                yield _sse_frame(event.type, event.id, event)
                cursor = max(cursor, event.id)
                last_yield = time.monotonic()
                if event.type in TERMINAL_EVENT_TYPES:
                    return
            if live_queue is not None:
                try:
                    event = live_queue.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(_LIVE_POLL_S)
                    continue
                if event.id <= cursor:
                    continue
                yield _sse_frame(event.type, event.id, event)
                cursor = event.id
                last_yield = time.monotonic()
                if event.type in TERMINAL_EVENT_TYPES:
                    return
                continue
            # Задача не в этом процессе (пауза пережила рестарт): поллим базу.
            await asyncio.sleep(_DB_POLL_S)
            if time.monotonic() - last_yield > _HEARTBEAT_S:
                yield b": heartbeat\n\n"
                last_yield = time.monotonic()
    except asyncio.CancelledError:  # клиент отключился
        raise
    finally:
        if live_queue is not None:
            manager.unsubscribe_live(run_id, live_queue)


@router.post("/runs/{run_id}/approval", response_model=AgentRunOut)
async def approve_agent_run(
    run_id: int,
    body: AgentApprovalIn,
    account: AccountContext = Depends(require_account_context),
) -> AgentRunOut:
    """Решение по карточке действия: «да» выполняет действие (с правкой текста), «нет» отклоняет."""
    try:
        edits = body.edits.model_dump(exclude_none=True) if body.edits is not None else None
        record = await get_runs_manager().approve(
            run_id=run_id, account_id=account.account_id, approved=body.approved, edits=edits
        )
    except DomainError as exc:
        raise to_http(exc) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    fresh = await runs_repo.get_run(run_id, account_id=account.account_id)
    return run_out(fresh or record)


@router.get("/settings", response_model=AgentSettingsOut)
async def get_agent_settings(
    account: AccountContext = Depends(require_account_context),
) -> AgentSettingsOut:
    """Настройки агента аккаунта: режим подтверждения действий (OQ-8)."""
    mode = await get_agent_confirm_mode(account_id=account.account_id)
    return AgentSettingsOut(confirm_mode="auto" if mode == "auto" else "ask")


@router.put("/settings", response_model=AgentSettingsOut)
async def put_agent_settings(
    body: AgentSettingsIn, account: AccountContext = Depends(require_account_context)
) -> AgentSettingsOut:
    """«Спрашивать каждый раз» / «подтверждать автоматически»; действует на следующие запуски."""
    try:
        await set_agent_confirm_mode(body.confirm_mode, account_id=account.account_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"БД недоступна: {exc}") from exc
    return AgentSettingsOut(confirm_mode=body.confirm_mode)
