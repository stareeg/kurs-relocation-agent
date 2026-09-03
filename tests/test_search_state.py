"""ST-01: режим поиска — журнал `search_state_log`, событие, лента, дефолт (без живой БД)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, get_args

import pytest

from core.app.subscriptions import register_domain_subscriptions
from core.domains.career.models import TimelineKind
from core.domains.career.search_state import (
    DEFAULT_MODE,
    MODE_LABELS,
    SearchMode,
    get_current_state,
    list_mode_history,
    set_search_mode,
)
from core.domains.career.timeline import timeline_from_search_mode_changed
from core.kernel import ports
from core.kernel.events import FIRST_ORDER_EVENTS, SearchModeChanged

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_0093 = ROOT / "core" / "platform" / "db" / "migrations" / "0093_search_state_log.sql"
MIGRATION_0094 = (
    ROOT / "core" / "platform" / "db" / "migrations" / "0094_search_state_retire_offer_endgame.sql"
)


class _FakeSearchStateDb:
    """Минимальный Executor под SQL search_state (select последней / insert / history)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self._seq = 0

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        s = " ".join(sql.lower().split())
        if s.startswith("insert into search_state_log"):
            self._seq += 1
            row = {
                "id": self._seq,
                "account_id": args[0],
                "mode": args[1],
                "prev_mode": args[2],
                "actor": args[3],
                "reason": args[4],
                "created_at": None,
            }
            self.rows.append(row)
            return dict(row)
        if s.startswith("select") and "from search_state_log" in s and "limit 1" in s:
            account_id = args[0]
            matches = [r for r in self.rows if r["account_id"] == account_id]
            return dict(matches[-1]) if matches else None
        raise AssertionError(f"unexpected fetchrow SQL: {sql!r} args={args!r}")

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        s = " ".join(sql.lower().split())
        if "from search_state_log" in s:
            account_id = args[0]
            matches = [r for r in self.rows if r["account_id"] == account_id]
            return [dict(r) for r in reversed(matches)][: args[1]]
        raise AssertionError(f"unexpected fetch SQL: {sql!r} args={args!r}")


@pytest.fixture(autouse=True)
def _clean_ports():
    ports.reset()
    yield
    ports.reset()


def test_migration_0093_search_state_log() -> None:
    # 0093 сам файл не правим (уже применён на части инсталляций) — offer_endgame в нём
    # исторически корректен, сужение канона до active/passive — отдельной миграцией 0094.
    assert MIGRATION_0093.is_file()
    text = MIGRATION_0093.read_text(encoding="utf-8")
    assert "create table search_state_log" in text
    for mode in ("'active'", "'passive'", "'offer_endgame'"):
        assert mode in text
    # Переход режима пишется в ленту — kind расширен в той же миграции.
    assert "'search_mode'" in text


def test_migration_0094_retires_offer_endgame() -> None:
    assert MIGRATION_0094.is_file()
    text = MIGRATION_0094.read_text(encoding="utf-8")
    assert "offer_endgame" in text  # переносит старые строки, а не молча их бросает
    assert "search_state_log_mode_check" in text
    assert "'active', 'passive'" in text


def test_timeline_kind_includes_search_mode() -> None:
    assert "search_mode" in set(get_args(TimelineKind))


def test_search_mode_changed_is_first_order() -> None:
    assert SearchModeChanged in FIRST_ORDER_EVENTS


def test_every_mode_has_label() -> None:
    """Каждый режим канона имеет человеческую подпись (заготовка sync-проверки ST-03)."""
    for mode in get_args(SearchMode):
        assert MODE_LABELS[mode].strip()


async def test_default_mode_when_log_empty() -> None:
    db = _FakeSearchStateDb()
    state = await get_current_state(account_id=1, db=db)
    assert state.mode == DEFAULT_MODE
    assert state.since is None
    assert state.label == MODE_LABELS[DEFAULT_MODE]


async def test_set_mode_appends_and_publishes() -> None:
    db = _FakeSearchStateDb()
    bus = ports.InProcessEventBus()
    seen: list[SearchModeChanged] = []
    bus.subscribe(SearchModeChanged, seen.append)

    with ports.use_ports(events=bus):
        entry = await set_search_mode("passive", account_id=1, actor="owner", db=db)

    assert entry.mode == "passive"
    assert entry.prev_mode is None
    assert len(db.rows) == 1
    assert len(seen) == 1
    evt = seen[0]
    assert evt.mode == "passive"
    assert evt.prev_mode == ""
    assert evt.actor == "owner"
    assert evt.subject == "passive"
    assert evt.account_id == 1

    state = await get_current_state(account_id=1, db=db)
    assert state.mode == "passive"


async def test_set_mode_again_records_transition() -> None:
    db = _FakeSearchStateDb()
    bus = ports.InProcessEventBus()
    seen: list[SearchModeChanged] = []
    bus.subscribe(SearchModeChanged, seen.append)

    with ports.use_ports(events=bus):
        await set_search_mode("passive", account_id=1, db=db)
        entry = await set_search_mode(
            "active", account_id=1, actor="suggestion", reason="снова активно", db=db
        )

    assert entry.prev_mode == "passive"
    assert entry.actor == "suggestion"
    assert len(db.rows) == 2
    assert len(seen) == 2
    assert seen[1].prev_mode == "passive"


async def test_reselect_same_mode_is_idempotent() -> None:
    db = _FakeSearchStateDb()
    bus = ports.InProcessEventBus()
    seen: list[SearchModeChanged] = []
    bus.subscribe(SearchModeChanged, seen.append)

    with ports.use_ports(events=bus):
        first = await set_search_mode("active", account_id=1, db=db)
        second = await set_search_mode("active", account_id=1, db=db)

    # Перевыбор текущего — ни новой строки, ни события.
    assert len(db.rows) == 1
    assert len(seen) == 1
    assert second.id == first.id


async def test_modes_are_isolated_per_account() -> None:
    """M5: режим одного аккаунта не виден/не переключается другим."""
    db = _FakeSearchStateDb()
    bus = ports.InProcessEventBus()
    with ports.use_ports(events=bus):
        await set_search_mode("passive", account_id=1, db=db)

    state_a = await get_current_state(account_id=1, db=db)
    state_b = await get_current_state(account_id=2, db=db)
    assert state_a.mode == "passive"
    assert state_b.mode == DEFAULT_MODE


async def test_history_returns_recent_first() -> None:
    db = _FakeSearchStateDb()
    bus = ports.InProcessEventBus()
    with ports.use_ports(events=bus):
        await set_search_mode("active", account_id=1, db=db)
        await set_search_mode("passive", account_id=1, db=db)

    history = await list_mode_history(account_id=1, db=db)
    assert [h.mode for h in history] == ["passive", "active"]


def test_timeline_mapper_for_mode_change() -> None:
    row = timeline_from_search_mode_changed(
        SearchModeChanged(mode="passive", prev_mode="active", actor="owner")
    )
    assert row is not None
    assert row.kind == "search_mode"
    assert row.title == f"Режим: {MODE_LABELS['active']} → {MODE_LABELS['passive']}"
    assert row.payload["prev_mode"] == "active"
    assert row.source_ref == "search_mode:passive"

    first = timeline_from_search_mode_changed(SearchModeChanged(mode="active"))
    assert first is not None
    assert first.title == f"Режим: {MODE_LABELS['active']}"

    assert timeline_from_search_mode_changed(SearchModeChanged()) is None


async def test_mode_change_subscription_writes_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Критерий ST-01: переход режима падает строкой в `career_timeline`."""
    inserted: list[object] = []

    async def _insert(event, *, account_id=None, db=None):
        inserted.append(event)
        return event

    monkeypatch.setattr(
        "core.domains.career.timeline.insert_timeline_event",
        _insert,
    )

    bus = ports.InProcessEventBus()
    register_domain_subscriptions(bus)
    await bus.publish_and_wait(
        SearchModeChanged(mode="passive", prev_mode="active", account_id=1)
    )

    assert len(inserted) == 1
    row = inserted[0]
    assert row.kind == "search_mode"
    assert row.payload["mode"] == "passive"
