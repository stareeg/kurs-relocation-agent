"""0152 / plans/career_redesign_2026_08_26.md, Этап 1: идемпотентность вставки в
`career_timeline` (только `kind="offer"`) и в `career_portfolio_items` (по `source_ref`).

Без реального Postgres (CLAUDE.md: тесты без DB-фикстур) — мини-модель таблиц в памяти,
повторяющая `on conflict (...) where ... do nothing` + фолбэк-select из
`core.domains.career.repo`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.domains.career.models import PortfolioItem, TimelineEvent
from core.domains.career.repo import insert_portfolio_item, insert_timeline_event

_NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


class FakeCareerDb:
    """Симулирует ровно те partial-unique-index конфликты, что заведены в 0152."""

    def __init__(self) -> None:
        self._timeline: list[dict[str, Any]] = []
        self._portfolio: list[dict[str, Any]] = []
        self._next_id = 1

    def _alloc_id(self) -> int:
        row_id = self._next_id
        self._next_id += 1
        return row_id

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        sql_l = " ".join(sql.lower().split())

        if sql_l.startswith("insert into career_timeline"):
            account_id, kind, title, occurred_at, payload, source_ref = args
            if kind == "offer" and source_ref:
                for row in self._timeline:
                    if row["account_id"] == account_id and row["source_ref"] == source_ref:
                        return None  # ON CONFLICT ... DO NOTHING — конфликт, строка не вернулась
            row = {
                "id": self._alloc_id(),
                "account_id": account_id,
                "kind": kind,
                "title": title,
                "occurred_at": occurred_at or _NOW,
                "payload": payload,
                "source_ref": source_ref,
                "created_at": _NOW,
            }
            self._timeline.append(row)
            return {k: v for k, v in row.items() if k != "account_id"}

        if "from career_timeline where account_id" in sql_l:
            account_id, kind, source_ref = args
            for row in self._timeline:
                if (
                    row["account_id"] == account_id
                    and row["kind"] == kind
                    and row["source_ref"] == source_ref
                ):
                    return {k: v for k, v in row.items() if k != "account_id"}
            return None

        if sql_l.startswith("insert into career_portfolio_items"):
            account_id, project, role, outcome, artifact_url, source_ref, notes = args
            if source_ref:
                for row in self._portfolio:
                    if row["account_id"] == account_id and row["source_ref"] == source_ref:
                        return None
            row = {
                "id": self._alloc_id(),
                "account_id": account_id,
                "project": project,
                "role": role,
                "outcome": outcome,
                "artifact_url": artifact_url,
                "source_ref": source_ref,
                "notes": notes,
                "created_at": _NOW,
                "updated_at": _NOW,
            }
            self._portfolio.append(row)
            return {k: v for k, v in row.items() if k != "account_id"}

        if "from career_portfolio_items where account_id" in sql_l:
            account_id, source_ref = args
            for row in self._portfolio:
                if row["account_id"] == account_id and row["source_ref"] == source_ref:
                    return {k: v for k, v in row.items() if k != "account_id"}
            return None

        raise AssertionError(f"unexpected SQL in FakeCareerDb: {sql}")


async def test_duplicate_offer_publish_returns_same_timeline_row() -> None:
    db = FakeCareerDb()
    evt = TimelineEvent(kind="offer", title="Оффер · Acme", source_ref="vac-1")

    first = await insert_timeline_event(evt, account_id=1, db=db)
    second = await insert_timeline_event(evt, account_id=1, db=db)

    assert first.id == second.id
    assert len(db._timeline) == 1


async def test_offer_dedupe_is_scoped_per_account() -> None:
    db = FakeCareerDb()
    evt = TimelineEvent(kind="offer", title="Оффер · Acme", source_ref="vac-1")

    a = await insert_timeline_event(evt, account_id=1, db=db)
    b = await insert_timeline_event(evt, account_id=2, db=db)

    assert a.id != b.id
    assert len(db._timeline) == 2


async def test_stage_kind_is_not_deduped_by_source_ref() -> None:
    """Разные этапы одной вакансии делят source_ref — это НЕ дубли, обе строки должны остаться."""
    db = FakeCareerDb()
    first = TimelineEvent(kind="stage", title="Отклик → Скрининг · vac-1", source_ref="vac-1")
    second = TimelineEvent(kind="stage", title="Скрининг → Техничка · vac-1", source_ref="vac-1")

    a = await insert_timeline_event(first, account_id=1, db=db)
    b = await insert_timeline_event(second, account_id=1, db=db)

    assert a.id != b.id
    assert len(db._timeline) == 2


async def test_duplicate_offer_portfolio_draft_returns_same_item() -> None:
    db = FakeCareerDb()
    item = PortfolioItem(project='Оффер · "МТС", Работа в IT', source_ref="offer:vac-1")

    first = await insert_portfolio_item(item, account_id=1, db=db)
    second = await insert_portfolio_item(item, account_id=1, db=db)

    assert first.id == second.id
    assert len(db._portfolio) == 1


async def test_manual_portfolio_items_without_source_ref_are_never_deduped() -> None:
    db = FakeCareerDb()
    item = PortfolioItem(project="Свой проект", source_ref="")

    a = await insert_portfolio_item(item, account_id=1, db=db)
    b = await insert_portfolio_item(item, account_id=1, db=db)

    assert a.id != b.id
    assert len(db._portfolio) == 2
