"""Э1.1: журнал треков поиска `search_track_log`, событие, лента, идемпотентность."""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

import pytest

from core.app.subscriptions import register_domain_subscriptions
from core.domains.career.models import TimelineKind
from core.domains.career.timeline import timeline_from_search_track_changed
from core.domains.career.track_state import (
    DEFAULT_TRACKS,
    TRACK_LABELS,
    get_current_tracks,
    set_second_job_enabled,
)
from core.kernel import ports
from core.kernel.events import FIRST_ORDER_EVENTS, SearchTrackChanged
from core.kernel.schemas.track import SearchTrack, normalize_tracks

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "core" / "platform" / "db" / "migrations" / "0132_search_track_log.sql"


class _FakeTrackDb:
    """Минимальный Executor под SQL search_track_log (select последней / insert)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._seq = 0

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.lower().split())
        if s.startswith("insert into search_track_log"):
            self._seq += 1
            row = {
                "id": self._seq,
                "account_id": args[0],
                "tracks": list(args[1]),
                "prev_tracks": list(args[2]),
                "actor": args[3],
                "reason": args[4],
                "created_at": None,
            }
            self.rows.append(row)
            return dict(row)
        if s.startswith("select") and "from search_track_log" in s and "limit 1" in s:
            account_id = args[0]
            matches = [r for r in self.rows if r["account_id"] == account_id]
            return dict(matches[-1]) if matches else None
        raise AssertionError(f"unexpected fetchrow SQL: {sql!r} args={args!r}")


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def test_migration_0132_search_track_log() -> None:
    assert MIGRATION.is_file()
    text = MIGRATION.read_text(encoding="utf-8")
    assert "create table search_track_log" in text
    assert "row level security" in text
    assert "'search_track'" in text
    assert "'primary'" in text
    assert "'second_job'" in text


def test_timeline_kind_includes_search_track() -> None:
    assert "search_track" in set(get_args(TimelineKind))


def test_search_track_changed_is_first_order() -> None:
    assert SearchTrackChanged in FIRST_ORDER_EVENTS


def test_every_track_has_label() -> None:
    for track in get_args(SearchTrack):
        assert TRACK_LABELS[track].strip()


def test_normalize_tracks_always_keeps_primary() -> None:
    assert normalize_tracks([]) == ["primary"]
    assert normalize_tracks(["second_job"]) == ["primary", "second_job"]
    assert normalize_tracks(["second_job", "primary", "nope"]) == ["primary", "second_job"]


async def test_default_tracks_when_log_empty() -> None:
    db = _FakeTrackDb()
    state = await get_current_tracks(account_id=1, db=db)
    assert state.tracks == list(DEFAULT_TRACKS)
    assert state.second_job_enabled is False
    assert state.since is None


async def test_set_tracks_appends_and_publishes() -> None:
    db = _FakeTrackDb()
    bus = ports.InProcessEventBus()
    seen: list[SearchTrackChanged] = []
    bus.subscribe(SearchTrackChanged, seen.append)

    with ports.use_ports(events=bus):
        entry = await set_second_job_enabled(True, account_id=1, actor="owner", db=db)

    assert entry.tracks == ["primary", "second_job"]
    assert entry.prev_tracks == []
    assert len(db.rows) == 1
    assert len(seen) == 1
    evt = seen[0]
    assert evt.tracks == ("primary", "second_job")
    assert evt.subject == "primary,second_job"
    assert evt.account_id == 1

    state = await get_current_tracks(account_id=1, db=db)
    assert state.second_job_enabled is True


async def test_reselect_same_tracks_is_idempotent() -> None:
    db = _FakeTrackDb()
    bus = ports.InProcessEventBus()
    seen: list[SearchTrackChanged] = []
    bus.subscribe(SearchTrackChanged, seen.append)

    with ports.use_ports(events=bus):
        first = await set_second_job_enabled(True, account_id=1, db=db)
        second = await set_second_job_enabled(True, account_id=1, db=db)

    assert len(db.rows) == 1
    assert len(seen) == 1
    assert second.id == first.id


async def test_disable_second_job_records_transition() -> None:
    db = _FakeTrackDb()
    bus = ports.InProcessEventBus()
    seen: list[SearchTrackChanged] = []
    bus.subscribe(SearchTrackChanged, seen.append)

    with ports.use_ports(events=bus):
        await set_second_job_enabled(True, account_id=1, db=db)
        entry = await set_second_job_enabled(False, account_id=1, db=db)

    assert entry.tracks == ["primary"]
    assert entry.prev_tracks == ["primary", "second_job"]
    assert len(db.rows) == 2
    assert len(seen) == 2


async def test_tracks_are_isolated_per_account() -> None:
    db = _FakeTrackDb()
    bus = ports.InProcessEventBus()
    with ports.use_ports(events=bus):
        await set_second_job_enabled(True, account_id=1, db=db)

    state_a = await get_current_tracks(account_id=1, db=db)
    state_b = await get_current_tracks(account_id=2, db=db)
    assert state_a.second_job_enabled is True
    assert state_b.second_job_enabled is False


def test_timeline_mapper_for_track_change() -> None:
    row = timeline_from_search_track_changed(
        SearchTrackChanged(
            tracks=("primary", "second_job"),
            prev_tracks=("primary",),
            actor="owner",
        )
    )
    assert row is not None
    assert row.kind == "search_track"
    assert "Основная" in row.title
    assert "Дополнительная" in row.title
    assert row.payload["tracks"] == ["primary", "second_job"]

    first = timeline_from_search_track_changed(
        SearchTrackChanged(tracks=("primary", "second_job"))
    )
    assert first is not None
    assert "→" not in first.title

    assert timeline_from_search_track_changed(SearchTrackChanged()) is not None


async def test_track_change_subscription_writes_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inserted: list[object] = []

    async def _insert(event, *, account_id=None, db=None):
        inserted.append(event)
        return event

    monkeypatch.setattr(
        "core.domains.career.timeline.insert_timeline_event",
        _insert,
    )
    monkeypatch.setattr(
        "core.domains.opportunities.rescore.schedule_rescore_all",
        lambda *a, **k: None,
    )

    async def _clear(*, account_id, db=None):
        return None

    monkeypatch.setattr(
        "core.domains.market.situation_store.clear_situation",
        _clear,
    )

    async def _refresh(*, account_id, force=False, db=None, llm=None):
        return None

    monkeypatch.setattr(
        "core.domains.profile.intl_experience.maybe_refresh_snapshot",
        _refresh,
    )

    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    await bus.publish_and_wait(
        SearchTrackChanged(
            tracks=("primary", "second_job"),
            prev_tracks=("primary",),
            account_id=1,
        )
    )

    assert len(inserted) == 1
    row = inserted[0]
    assert row.kind == "search_track"
    assert row.payload["tracks"] == ["primary", "second_job"]


def test_set_tracks_drops_only_second_job() -> None:
    """Основной трек нельзя выключить, передав только second_job."""
    assert normalize_tracks(["second_job"])[0] == "primary"
