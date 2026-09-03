"""TB-4.1 / TB-4.7: forward_batcher — debounce-склейка, cap, одиночный форвард без батча."""

from __future__ import annotations

import asyncio

import pytest

from bot_app.services.forward_batcher import ForwardBatcher


@pytest.mark.asyncio
async def test_single_forward_flushes_alone_after_debounce() -> None:
    """Одиночный форвард: один push → один on_batch с одним элементом (без склейки)."""
    batcher: ForwardBatcher[str] = ForwardBatcher(debounce_sec=0.05, max_items=30, name="t")
    received: list[list[str]] = []

    async def on_batch(items: list[str]) -> None:
        received.append(list(items))

    await batcher.push(1, "solo", on_batch)
    assert received == []
    await asyncio.sleep(0.12)
    assert received == [["solo"]]
    assert len(received[0]) == 1


@pytest.mark.asyncio
async def test_debounce_merges_rapid_pushes() -> None:
    """Debounce-склейка: быстрые push в один чат → один батч."""
    batcher: ForwardBatcher[str] = ForwardBatcher(debounce_sec=0.08, max_items=30, name="t")
    received: list[list[str]] = []

    async def on_batch(items: list[str]) -> None:
        received.append(list(items))

    await batcher.push(7, "one", on_batch)
    await asyncio.sleep(0.03)
    await batcher.push(7, "two", on_batch)
    await asyncio.sleep(0.03)
    await batcher.push(7, "three", on_batch)
    assert received == []
    await asyncio.sleep(0.12)
    assert received == [["one", "two", "three"]]


@pytest.mark.asyncio
async def test_chats_are_isolated() -> None:
    batcher: ForwardBatcher[int] = ForwardBatcher(debounce_sec=0.05, max_items=30, name="t")
    by_chat: dict[int, list[int]] = {}

    def make_cb(chat_id: int):
        async def on_batch(items: list[int]) -> None:
            by_chat[chat_id] = list(items)

        return on_batch

    await batcher.push(10, 1, make_cb(10))
    await batcher.push(20, 2, make_cb(20))
    await batcher.push(10, 3, make_cb(10))
    await asyncio.sleep(0.12)
    assert by_chat == {10: [1, 3], 20: [2]}


@pytest.mark.asyncio
async def test_cap_flushes_immediately_without_waiting() -> None:
    """Cap: при max_items flush сразу, без ожидания debounce."""
    batcher: ForwardBatcher[int] = ForwardBatcher(debounce_sec=5.0, max_items=3, name="t")
    received: list[list[int]] = []

    async def on_batch(items: list[int]) -> None:
        received.append(list(items))

    await batcher.push(1, 1, on_batch)
    await batcher.push(1, 2, on_batch)
    assert received == []
    await batcher.push(1, 3, on_batch)
    assert received == [[1, 2, 3]]


@pytest.mark.asyncio
async def test_cap_then_next_batch_starts_fresh() -> None:
    batcher: ForwardBatcher[str] = ForwardBatcher(debounce_sec=0.05, max_items=2, name="t")
    received: list[list[str]] = []

    async def on_batch(items: list[str]) -> None:
        received.append(list(items))

    await batcher.push(1, "a", on_batch)
    await batcher.push(1, "b", on_batch)
    assert received == [["a", "b"]]
    await batcher.push(1, "c", on_batch)
    await asyncio.sleep(0.1)
    assert received == [["a", "b"], ["c"]]


@pytest.mark.asyncio
async def test_hr_style_join_preserves_anchor() -> None:
    """Поведение HR-пути: склейка \\n\\n, якорь = последний message_id."""
    batcher: ForwardBatcher[tuple[str, int]] = ForwardBatcher(
        debounce_sec=0.05, max_items=30, name="hr"
    )
    result: list[tuple[str, int]] = []

    async def on_batch(items: list[tuple[str, int]]) -> None:
        combined = "\n\n".join(t for t, _ in items if t)
        result.append((combined, items[-1][1]))

    await batcher.push(1, ("hello", 10), on_batch)
    await batcher.push(1, ("world", 11), on_batch)
    await asyncio.sleep(0.1)
    assert result == [("hello\n\nworld", 11)]


@pytest.mark.asyncio
async def test_on_batch_error_does_not_poison_next_push() -> None:
    """Сбой on_batch не оставляет «грязный» бакет — следующий push собирается заново."""
    batcher: ForwardBatcher[str] = ForwardBatcher(debounce_sec=0.05, max_items=30, name="t")
    calls = 0
    received: list[list[str]] = []

    async def on_batch(items: list[str]) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        received.append(list(items))

    await batcher.push(1, "bad", on_batch)
    await asyncio.sleep(0.12)
    assert calls == 1
    assert received == []

    await batcher.push(1, "ok", on_batch)
    await asyncio.sleep(0.12)
    assert received == [["ok"]]


def test_invalid_ctor_args() -> None:
    with pytest.raises(ValueError):
        ForwardBatcher(debounce_sec=0)
    with pytest.raises(ValueError):
        ForwardBatcher(max_items=0)
