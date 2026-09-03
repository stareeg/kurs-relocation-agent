"""Лента карьеры — `GET/POST /api/career/timeline` (Э9.3, обогащение и курсор — Этап 2 плана
`plans/career_redesign_2026_08_26.md`).

`career_timeline` уже пишется подписчиками (`career/events.py`); этому роутеру не хватало
только чтения и одного ручного действия всего экрана — добавить событие.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.schemas import TimelineEventCreate, TimelineEventView
from api.security import AccountContext, require_account_context
from core.app.scenarios.career_timeline_view import load_vacancy_refs
from core.domains.career.models import TimelineEvent
from core.domains.career.repo import list_timeline_events
from core.domains.career.timeline import append_timeline_event

router = APIRouter(prefix="/api/career", tags=["career"])


@router.get("/timeline", response_model=list[TimelineEventView])
async def timeline_list(
    limit: int = Query(default=100, ge=1, le=500),
    kinds: str | None = Query(default=None, description="Виды через запятую"),
    before_id: int | None = Query(
        default=None, description="Курсор «Показать ещё»: id последней увиденной строки"
    ),
    account: AccountContext = Depends(require_account_context),
) -> list[TimelineEventView]:
    """Лента аккаунта, свежие первыми. `kinds=stage,offer` — фильтр по видам; `before_id` —
    продолжить с элемента после этой строки (та же сортировка, что и без курсора)."""
    kind_list = [k.strip() for k in kinds.split(",") if k.strip()] if kinds else None
    events = await list_timeline_events(
        account_id=account.account_id, limit=limit, kinds=kind_list, before_id=before_id
    )
    refs = await load_vacancy_refs(events, account_id=account.account_id)
    views: list[TimelineEventView] = []
    for ev in events:
        vacancy_id = str(ev.payload.get("vacancy_id") or "").strip()
        ref = refs.get(vacancy_id)
        views.append(
            TimelineEventView(
                **ev.model_dump(),
                company=ref.company if ref else "",
                vacancy_title=ref.title if ref else "",
                href=f"/chat?vacancy={vacancy_id}" if vacancy_id else None,
            )
        )
    return views


@router.post("/timeline", response_model=TimelineEvent)
async def timeline_create(
    body: TimelineEventCreate,
    account: AccountContext = Depends(require_account_context),
) -> TimelineEvent:
    """Единственное ручное действие всего экрана «Карьера» — добавить событие вручную."""
    event = TimelineEvent(kind=body.kind, title=body.title, occurred_at=body.occurred_at)
    return await append_timeline_event(event, account_id=account.account_id)
