"""Единый SSE-контракт стриминга.

Media type: ``text/event-stream``.
Канонические события: ``part`` / ``progress`` / ``done`` / ``error``.
Heartbeat: SSE-комментарий ``: heartbeat`` каждые 15 с (клиент игнорирует).
``id:`` — монотонный seq для ``Last-Event-ID`` (переподключение — L-39).

Доменный payload кладётся в ``data`` как JSON; семантический подтип — поле ``type``
внутри data (как раньше в NDJSON). Транспортный слой только кодирует и классифицирует.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from fastapi.responses import StreamingResponse

HEARTBEAT_INTERVAL_S = 15.0
SSE_MEDIA_TYPE = "text/event-stream"
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

CANONICAL_EVENTS = frozenset({"part", "progress", "done", "error"})

# Доменный ``type`` → SSE ``event:``. Неизвестное → ``part``.
_TYPE_TO_EVENT: dict[str, str] = {
    "status": "progress",
    "start": "progress",
    "progress": "progress",
    "node_start": "progress",
    "brief": "part",
    "pitch": "part",
    "questions": "part",
    "token": "part",
    "result": "part",
    "part_error": "part",
    "done": "done",
    "complete": "done",
    "error": "error",
}


def classify_event(payload: Mapping[str, Any], *, default: str = "part") -> str:
    """Выбрать каноническое SSE-событие по ``payload['type']``."""
    raw = payload.get("type")
    if isinstance(raw, str):
        mapped = _TYPE_TO_EVENT.get(raw)
        if mapped is not None:
            return mapped
    return default


def normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Нормализовать алиасы (negotiations ``complete`` → ``done``)."""
    data = dict(payload)
    if data.get("type") == "complete":
        data["type"] = "done"
    return data


def format_sse(
    event: str,
    data: Mapping[str, Any],
    *,
    seq: int | None = None,
) -> bytes:
    """Один кадр Server-Sent Events (UTF-8)."""
    if event not in CANONICAL_EVENTS:
        raise ValueError(f"неканоническое SSE-событие: {event!r}")
    lines: list[str] = []
    if seq is not None:
        lines.append(f"id: {seq}")
    lines.append(f"event: {event}")
    payload = json.dumps(data, ensure_ascii=False)
    for line in payload.split("\n"):
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines).encode("utf-8")


async def iter_sse(
    source: AsyncIterator[Mapping[str, Any]],
    *,
    heartbeat_s: float = HEARTBEAT_INTERVAL_S,
    classify: Callable[[Mapping[str, Any]], str] | None = None,
    transform: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> AsyncIterator[bytes]:
    """Кодировать доменные dict-события в SSE с heartbeat и seq.

    ``source`` — async-итератор payload'ов с полем ``type`` (как прежний NDJSON).
    """
    classify_fn = classify or classify_event
    transform_fn = transform or normalize_payload
    seq = 0
    agen = source.__aiter__()

    async def _pull() -> Mapping[str, Any]:
        return await agen.__anext__()

    pending: asyncio.Task[Mapping[str, Any]] | None = asyncio.create_task(_pull())

    try:
        while pending is not None:
            timeout = None if heartbeat_s <= 0 else heartbeat_s
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if not done:
                yield b": heartbeat\n\n"
                continue
            try:
                raw = pending.result()
            except StopAsyncIteration:
                pending = None
                break
            payload = transform_fn(raw)
            event = classify_fn(payload)
            yield format_sse(event, payload, seq=seq)
            seq += 1
            pending = asyncio.create_task(_pull())
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration, Exception):
                await pending


def sse_response(
    source: AsyncIterator[Mapping[str, Any]],
    *,
    heartbeat_s: float = HEARTBEAT_INTERVAL_S,
    classify: Callable[[Mapping[str, Any]], str] | None = None,
    transform: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
) -> StreamingResponse:
    """``StreamingResponse`` с единым media type и заголовками."""
    return StreamingResponse(
        iter_sse(
            source,
            heartbeat_s=heartbeat_s,
            classify=classify,
            transform=transform,
        ),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )


def wants_sse(accept: str | None) -> bool:
    """Клиент просит SSE (``Accept: text/event-stream``)."""
    return "text/event-stream" in (accept or "").lower()
