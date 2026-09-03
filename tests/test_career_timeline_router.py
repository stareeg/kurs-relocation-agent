"""Лента карьеры — `GET/POST /api/career/timeline` (Э9.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.routers.career.timeline import timeline_create, timeline_list
from api.schemas.career import ManualTimelineKind, TimelineEventCreate
from api.security import AccountContext

_ACCOUNT = AccountContext(account_id=1, telegram_user_id=1, telegram_username=None, role="owner")


def test_manual_kind_accepts_only_manual_safe_values() -> None:
    for kind in ("job_start", "promotion", "project", "certificate", "relocation", "other"):
        TimelineEventCreate(kind=kind, title="Тест")  # не падает


@pytest.mark.parametrize(
    "system_kind", ["application", "stage", "offer", "search_mode", "search_track"]
)
def test_manual_kind_rejects_system_kinds(system_kind: str) -> None:
    """Системные виды пишутся только подписчиками событий, не ручной формой."""
    with pytest.raises(ValidationError):
        TimelineEventCreate(kind=system_kind, title="Тест")


def test_manual_kind_covers_exactly_the_non_system_kinds() -> None:
    """Синхро-якорь: ManualTimelineKind не должен расходиться с TimelineKind модели."""
    from typing import get_args

    from core.domains.career.models import TimelineKind

    system_kinds = {"application", "stage", "offer", "search_mode", "search_track"}
    assert set(get_args(ManualTimelineKind)) == set(get_args(TimelineKind)) - system_kinds


async def test_timeline_create_calls_append_with_account_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    async def _append(event, *, account_id, db=None):
        calls.append({"event": event, "account_id": account_id})
        return event

    monkeypatch.setattr("api.routers.career.timeline.append_timeline_event", _append)

    body = TimelineEventCreate(kind="job_start", title="Вышел на работу")
    result = await timeline_create(body, account=_ACCOUNT)

    assert len(calls) == 1
    assert calls[0]["account_id"] == 1
    assert result.kind == "job_start"
    assert result.title == "Вышел на работу"


async def test_timeline_list_parses_comma_separated_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _list(*, account_id, limit, kinds=None, before_id=None, db=None):
        captured["account_id"] = account_id
        captured["limit"] = limit
        captured["kinds"] = kinds
        captured["before_id"] = before_id
        return []

    monkeypatch.setattr("api.routers.career.timeline.list_timeline_events", _list)

    await timeline_list(limit=50, kinds="stage, offer ,other", before_id=None, account=_ACCOUNT)

    assert captured == {
        "account_id": 1,
        "limit": 50,
        "kinds": ["stage", "offer", "other"],
        "before_id": None,
    }


async def test_timeline_list_no_kinds_filter_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _list(*, account_id, limit, kinds=None, before_id=None, db=None):
        captured["kinds"] = kinds
        return []

    monkeypatch.setattr("api.routers.career.timeline.list_timeline_events", _list)

    await timeline_list(limit=100, kinds=None, before_id=None, account=_ACCOUNT)

    assert captured["kinds"] is None


async def test_timeline_list_forwards_before_id_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def _list(*, account_id, limit, kinds=None, before_id=None, db=None):
        captured["before_id"] = before_id
        return []

    monkeypatch.setattr("api.routers.career.timeline.list_timeline_events", _list)

    await timeline_list(limit=30, kinds=None, before_id=42, account=_ACCOUNT)

    assert captured["before_id"] == 42


async def test_timeline_list_enriches_events_with_vacancy_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Этап 2: title остаётся сырым (мапперы не трогаем), но company/vacancy_title/href
    заполняются на чтении, когда вакансия резолвится."""
    from core.domains.career.models import TimelineEvent
    from core.app.scenarios.career_timeline_view import VacancyRef

    resolved = TimelineEvent(
        kind="offer", title="Оффер · vac-1", source_ref="vac-1", payload={"vacancy_id": "vac-1"}
    )
    unresolved = TimelineEvent(
        kind="stage", title="Отклик → Скрининг · vac-2", payload={"vacancy_id": "vac-2"}
    )

    async def _list(*, account_id, limit, kinds=None, before_id=None, db=None):
        return [resolved, unresolved]

    async def _refs(events, *, account_id):
        return {"vac-1": VacancyRef(company="Acme", title="Backend-разработчик")}

    monkeypatch.setattr("api.routers.career.timeline.list_timeline_events", _list)
    monkeypatch.setattr("api.routers.career.timeline.load_vacancy_refs", _refs)

    views = await timeline_list(limit=30, kinds=None, before_id=None, account=_ACCOUNT)

    assert views[0].company == "Acme"
    assert views[0].vacancy_title == "Backend-разработчик"
    assert views[0].href == "/chat?vacancy=vac-1"
    assert views[1].company == ""
    assert views[1].vacancy_title == ""
    assert views[1].href == "/chat?vacancy=vac-2"
