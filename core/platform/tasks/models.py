"""Модели очереди фоновых задач. Без I/O — только формы данных."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRecord(BaseModel):
    """Строка очереди — то, что видит UI и воркер."""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: str
    idempotency_key: str | None = None
    priority: int = 100
    payload: dict[str, Any] = Field(default_factory=dict)
    # None — системная задача (GC, маркет-агрегация, cron-уборка): не принадлежит ни одному
    # аккаунту по смыслу (plans/multitenancy_gaps_2026_08_06.md §3.10).
    account_id: int | None = None
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    max_attempts: int = 3
    run_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str = ""
    created_at: datetime
    updated_at: datetime


class CronSpec(BaseModel):
    """Ежедневное расписание → enqueue с ключом ``{schedule_id}:{YYYY-MM-DD}``."""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    hour: int
    minute: int
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    misfire_grace_sec: int = 3600
    enabled: bool = True


__all__ = ["CronSpec", "TaskRecord", "TaskStatus"]
