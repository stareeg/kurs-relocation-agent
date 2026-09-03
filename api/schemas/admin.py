"""Транспорт админ-консоли: реэкспорт моделей platform + тела мутаций."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from core.platform.admin.models import (
    AdminAccountSnapshot,
    AdminAttention,
    AdminAuditPage,
    AdminAuditRow,
    AdminCount,
    AdminDeviceSession,
    AdminDiagnosis,
    AdminDiagnosisItem,
    AdminErrorBurst,
    AdminHealth,
    AdminHealthQueue,
    AdminKeyBalance,
    AdminKeyBalances,
    AdminKeyHistory,
    AdminKeyRequest,
    AdminKeyVerify,
    AdminLogPage,
    AdminLogRow,
    AdminNoKeyWait,
    AdminOnboardingFunnel,
    AdminPartial,
    AdminPeoplePage,
    AdminPipelineBrief,
    AdminPipelinePlatform,
    AdminRecentAction,
    AdminSpend,
    AdminSpendAlert,
    AdminSpendOver,
    AdminSpendRow,
    AdminSpendSegment,
    AdminStaleAccount,
    AdminSummary,
    AdminSupportMessage,
    AdminSupportThread,
    AdminTables,
    AdminTableSize,
    AdminTaskDetail,
    AdminTaskKindCount,
    AdminTaskReasonCount,
    AdminTaskRow,
    AdminTasks,
    AdminTelegramSent,
    AdminUserDetail,
    AdminUserPipeline,
    AdminUserRow,
    FunnelCounts,
)


class AdminOk(BaseModel):
    ok: bool = True


class AdminRevokeResponse(BaseModel):
    revoked: int


class AdminTelegramRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3500)


class AdminSupportSendRequest(BaseModel):
    """Реплика оператора в ленте поддержки: человеку (Telegram) или агенту."""

    channel: Literal["user", "agent"]
    text: str = Field(min_length=1, max_length=3500)
    reply_to_id: int | None = None


class AdminKeyIssueRequest(BaseModel):
    """Выдача/перевыпуск ключа. `label` — как ключ назван в кабинете OpenRouter: маска в
    консоли отвечает «какой это ключ», метка — «какой из них гасить, если что»."""

    key: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=120)


class AdminKeyVerifyRequest(BaseModel):
    """Тело проверки до выдачи. Ответ — `AdminKeyVerify`, без сырого ключа."""

    key: str = Field(min_length=1)


class AdminDisableRequest(BaseModel):
    """Причина отключения — через полгода иначе не ответить, почему человек выключен."""

    reason: str = Field(default="", max_length=500)


class AdminNoteRequest(BaseModel):
    """Заметка оператора. Пустая строка стирает."""

    note: str = Field(default="", max_length=500)


class AdminRoleRequest(BaseModel):
    role: str = Field(pattern="^(owner|member)$")


class AdminDiscoveryStopRequest(BaseModel):
    """Остановить автопросмотр пользователя — одну площадку или (пусто) все три."""

    platform: Literal["hh", "getmatch", "habr"] | None = None


class AdminPipelineCount(BaseModel):
    """Сколько вакансий затронуто операторской очисткой очереди автооткликов."""

    cleared: int = 0


class AdminDiscoveryStopResponse(BaseModel):
    stopped: list[str] = Field(default_factory=list)


class AdminLogsQuery(BaseModel):
    """Параметры GET /api/admin/logs. Капы (окно, limit, длина q) — в сервисе."""

    since: datetime | None = None
    until: datetime | None = None
    level: str = ""
    account_id: int | None = Field(default=None, ge=1)
    telegram_user_id: int | None = Field(default=None, ge=1)
    logger: str = Field(default="", max_length=120)
    event: str = Field(default="", max_length=80)
    q: str = Field(default="", max_length=200)
    cursor: str = Field(default="", max_length=120)
    limit: int = Field(default=100, ge=1, le=200)


class AdminAuditQuery(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    account_id: int | None = Field(default=None, ge=1)
    telegram_user_id: int | None = Field(default=None, ge=1)
    cursor: str = Field(default="", max_length=120)
    limit: int = Field(default=100, ge=1, le=200)


class AdminTasksQuery(BaseModel):
    status: str = Field(default="", pattern="^(pending|running|failed|done|cancelled)?$")
    kind: str = Field(default="", max_length=80)
    limit: int = Field(default=40, ge=1, le=200)


class AdminTaskRetryKindRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=120)


class AdminTaskCancelKindRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=80)
    reason: str = Field(default="", max_length=120)


class AdminPurgeRequest(BaseModel):
    days: Literal[30, 60, 90]


class AdminSpendAlertRequest(BaseModel):
    """Мягкий порог за календарный месяц. 0 выключает сигнал, LLM не отсекаем."""

    usd: float = Field(ge=0, le=10_000)


class AdminExtensionRuntimeConfig(BaseModel):
    """Рантайм-конфиг расширения (merged): флаги, тюнинг, селекторы отклика/разбора, текстовые
    сигналы + замечания валидации последнего оверрайда."""

    version: int
    origin: str
    updated_at: str
    flags: dict[str, bool]
    tuning: dict[str, Any]
    apply_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    parse_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    text_signals: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class AdminExtensionRuntimeConfigRequest(BaseModel):
    """Оверрайд рантайм-конфига. Все секции опциональны; все пустые = снять оверрайд."""

    flags: dict[str, bool] = Field(default_factory=dict)
    tuning: dict[str, Any] = Field(default_factory=dict)
    apply_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    parse_selectors: dict[str, dict[str, str]] = Field(default_factory=dict)
    text_signals: dict[str, dict[str, list[str]]] = Field(default_factory=dict)


__all__ = [
    "AdminAccountSnapshot",
    "AdminAttention",
    "AdminAuditPage",
    "AdminAuditQuery",
    "AdminAuditRow",
    "AdminCount",
    "AdminDeviceSession",
    "AdminDiagnosis",
    "AdminDiagnosisItem",
    "AdminDisableRequest",
    "AdminDiscoveryStopRequest",
    "AdminDiscoveryStopResponse",
    "AdminErrorBurst",
    "AdminExtensionRuntimeConfig",
    "AdminExtensionRuntimeConfigRequest",
    "AdminHealth",
    "AdminHealthQueue",
    "AdminKeyBalance",
    "AdminKeyBalances",
    "AdminKeyHistory",
    "AdminKeyIssueRequest",
    "AdminKeyRequest",
    "AdminKeyVerify",
    "AdminKeyVerifyRequest",
    "AdminLogPage",
    "AdminLogRow",
    "AdminLogsQuery",
    "AdminNoKeyWait",
    "AdminNoteRequest",
    "AdminOk",
    "AdminOnboardingFunnel",
    "AdminPartial",
    "AdminPeoplePage",
    "AdminPipelineBrief",
    "AdminPipelineCount",
    "AdminPipelinePlatform",
    "AdminPurgeRequest",
    "AdminRecentAction",
    "AdminRevokeResponse",
    "AdminRoleRequest",
    "AdminSpend",
    "AdminSpendAlert",
    "AdminSpendAlertRequest",
    "AdminSpendOver",
    "AdminSpendRow",
    "AdminSpendSegment",
    "AdminStaleAccount",
    "AdminSummary",
    "AdminSupportMessage",
    "AdminSupportSendRequest",
    "AdminSupportThread",
    "AdminTableSize",
    "AdminTables",
    "AdminTaskDetail",
    "AdminTaskKindCount",
    "AdminTaskCancelKindRequest",
    "AdminTaskReasonCount",
    "AdminTaskRetryKindRequest",
    "AdminTaskRow",
    "AdminTasks",
    "AdminTasksQuery",
    "AdminTelegramRequest",
    "AdminTelegramSent",
    "AdminUserDetail",
    "AdminUserPipeline",
    "AdminUserRow",
    "FunnelCounts",
]
