"""Единый SSE-контракт: кодирование, классификация, heartbeat."""

from __future__ import annotations

import asyncio

import pytest

from api.streaming import (
    HEARTBEAT_INTERVAL_S,
    classify_event,
    format_sse,
    iter_sse,
    normalize_payload,
    wants_sse,
)


def test_classify_event_maps_domain_types() -> None:
    assert classify_event({"type": "token"}) == "part"
    assert classify_event({"type": "status"}) == "progress"
    assert classify_event({"type": "start"}) == "progress"
    assert classify_event({"type": "progress"}) == "progress"
    assert classify_event({"type": "done"}) == "done"
    assert classify_event({"type": "complete"}) == "done"
    assert classify_event({"type": "error"}) == "error"
    assert classify_event({"type": "unknown_thing"}) == "part"
    assert classify_event({}) == "part"


def test_normalize_complete_to_done() -> None:
    assert normalize_payload({"type": "complete", "response": {}}) == {
        "type": "done",
        "response": {},
    }


def test_format_sse_frame() -> None:
    raw = format_sse("part", {"type": "token", "text": "привет"}, seq=7)
    text = raw.decode("utf-8")
    assert text.startswith("id: 7\n")
    assert "event: part\n" in text
    assert '"type": "token"' in text
    assert '"text": "привет"' in text
    assert text.endswith("\n\n")


def test_format_sse_rejects_noncanonical() -> None:
    with pytest.raises(ValueError, match="неканоническое"):
        format_sse("token", {"text": "x"})


def test_wants_sse() -> None:
    assert wants_sse("text/event-stream")
    assert wants_sse("application/json, text/event-stream")
    assert not wants_sse("application/x-ndjson")
    assert not wants_sse(None)


@pytest.mark.asyncio
async def test_iter_sse_emits_seq_and_canonical_events() -> None:
    async def source():
        yield {"type": "status", "label": "старт"}
        yield {"type": "token", "text": "a"}
        yield {"type": "done", "status": "done"}

    frames = [frame async for frame in iter_sse(source(), heartbeat_s=0)]
    texts = [f.decode("utf-8") for f in frames]
    assert len(texts) == 3
    assert "id: 0\n" in texts[0] and "event: progress\n" in texts[0]
    assert "id: 1\n" in texts[1] and "event: part\n" in texts[1]
    assert "id: 2\n" in texts[2] and "event: done\n" in texts[2]


@pytest.mark.asyncio
async def test_iter_sse_heartbeat_comment() -> None:
    async def slow():
        await asyncio.sleep(0.05)
        yield {"type": "done", "status": "done"}

    frames = [frame async for frame in iter_sse(slow(), heartbeat_s=0.01)]
    assert any(f == b": heartbeat\n\n" for f in frames)
    assert any(b"event: done" in f for f in frames)


def test_heartbeat_interval_default() -> None:
    assert HEARTBEAT_INTERVAL_S == 15.0
