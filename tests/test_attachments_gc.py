"""Э0-5: GC-задача несвязанных вложений — пагинация по батчам, TTL из настроек.

`repo.gc_candidates`/`delete_attachments` монкейпатчатся напрямую (без DB, CLAUDE.md);
здесь важно поведение самой задачи (`_run_attachments_gc`), а не SQL репозитория — тот уже
покрыт `tests/test_attachments_repo.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from core.domains.assistant.attachments import gc


class _FakeSettings:
    attachment_gc_after_hours = 24


async def test_gc_deletes_all_pages_until_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Меньше кандидатов, чем батч, за один проход — не зацикливается."""
    pages = [[1, 2, 3]]
    deleted: list[list[int]] = []

    async def fake_candidates(*, older_than: datetime, limit: int, db: Any = None) -> list[int]:
        assert older_than.tzinfo is not None
        return pages.pop(0) if pages else []

    async def fake_delete(ids: list[int], *, db: Any = None) -> int:
        deleted.append(ids)
        return len(ids)

    monkeypatch.setattr(gc, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(gc.repo, "gc_candidates", fake_candidates)
    monkeypatch.setattr(gc.repo, "delete_attachments", fake_delete)

    await gc._run_attachments_gc({})

    assert deleted == [[1, 2, 3]]


async def test_gc_pages_through_full_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Полный батч → запрашиваем следующую страницу, пока не придёт пустая/неполная."""
    monkeypatch.setattr(gc, "_BATCH_SIZE", 2)
    pages = [[1, 2], [3, 4], [5]]
    deleted: list[list[int]] = []

    async def fake_candidates(*, older_than: datetime, limit: int, db: Any = None) -> list[int]:
        assert limit == 2
        return pages.pop(0) if pages else []

    async def fake_delete(ids: list[int], *, db: Any = None) -> int:
        deleted.append(list(ids))
        return len(ids)

    monkeypatch.setattr(gc, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(gc.repo, "gc_candidates", fake_candidates)
    monkeypatch.setattr(gc.repo, "delete_attachments", fake_delete)

    await gc._run_attachments_gc({})

    assert deleted == [[1, 2], [3, 4], [5]]


async def test_gc_no_candidates_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def fake_candidates(*, older_than: datetime, limit: int, db: Any = None) -> list[int]:
        return []

    async def fake_delete(ids: list[int], *, db: Any = None) -> int:
        nonlocal calls
        calls += 1
        return 0

    monkeypatch.setattr(gc, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(gc.repo, "gc_candidates", fake_candidates)
    monkeypatch.setattr(gc.repo, "delete_attachments", fake_delete)

    await gc._run_attachments_gc({})

    assert calls == 0


async def test_gc_cutoff_uses_configured_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_candidates(*, older_than: datetime, limit: int, db: Any = None) -> list[int]:
        captured["older_than"] = older_than
        return []

    monkeypatch.setattr(gc, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(gc.repo, "gc_candidates", fake_candidates)

    before = datetime.now(UTC)
    await gc._run_attachments_gc({})
    age_hours = (before - captured["older_than"]).total_seconds() / 3600
    assert 23.9 < age_hours < 24.1
