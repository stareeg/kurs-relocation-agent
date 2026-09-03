"""Витрина фоновых задач очереди A-20 — GET /api/background-tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.schemas import BackgroundTaskItem, BackgroundTasksResponse
from api.security import AccountContext, require_account_context
from core.platform.tasks import TaskRecord, get_runtime

router = APIRouter(prefix="/api", tags=["tasks"])


def _task_item(r: TaskRecord) -> BackgroundTaskItem:
    return BackgroundTaskItem(
        id=r.id,
        kind=r.kind,
        status=r.status.value,
        priority=r.priority,
        attempts=r.attempts,
        max_attempts=r.max_attempts,
        idempotency_key=r.idempotency_key,
        run_at=r.run_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        last_error=r.last_error,
        created_at=r.created_at,
    )


@router.get("/background-tasks", response_model=BackgroundTasksResponse)
async def list_background_tasks(
    limit: int = Query(40, ge=1, le=200),
    account: AccountContext = Depends(require_account_context),
) -> BackgroundTasksResponse:
    """Последние задачи очереди (приоритет, статус, ретраи) для вкладки «Параметры»: свои
    account-задачи + системные (GC, маркет-агрегация, cron-уборка) — не чужие."""
    rows = await get_runtime().list_recent(limit=limit, account_id=account.account_id)
    return BackgroundTasksResponse(items=[_task_item(r) for r in rows])
