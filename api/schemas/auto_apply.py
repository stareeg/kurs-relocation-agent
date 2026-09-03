"""Транспортные схемы API: настройки и превью очереди автооткликов.

Конфиг переиспользуем из ядра (`core.domains.pipeline.auto_apply`) — доменные модели уже
Pydantic и не содержат I/O, дублировать их здесь незачем.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from core.domains.opportunities.models import AnketaAnswer, AnketaQuestion, AnketaState
from core.domains.pipeline.auto_apply import (
    AutoApplyConfig,
    AutoApplyDecision,
    AutoApplyPlatform,
    AutoApplyPlatformConfig,
    QueueOverride,
)

__all__ = [
    "AnketaConfirmRequest",
    "AnketaPendingItem",
    "AnketaPendingResponse",
    "AutoApplyClearResponse",
    "AutoApplyConfig",
    "AutoApplyDailyCountResponse",
    "AutoApplyDecision",
    "AutoApplyManualSendResponse",
    "AutoApplyMoveRequest",
    "AutoApplyPlatform",
    "AutoApplyPlatformConfig",
    "AutoApplyPauseResponse",
    "AutoApplyPreviewItem",
    "AutoApplyPreviewResponse",
    "AutoApplyReportRequest",
    "AutoApplyReportResponse",
    "AutoApplySchedule",
    "AutoApplyTickReport",
    "QueueOverride",
]


class AutoApplyPreviewItem(BaseModel):
    """Одна вакансия в превью очереди автооткликов."""

    job_id: int
    vacancy_id: str
    url: str | None = None
    title: str | None = None
    company: str | None = None
    overall_score: int | None = None
    decision: AutoApplyDecision
    # Фаза E редизайна «Расширения» (пункт 4) — иконки «Сопроводительное»/«Анкета» на строке
    # очереди: денормализация тех же полей `Job`, что и `AnketaPendingItem._anketa_item` ниже, но
    # для ВСЕЙ превью-очереди, не только тех, что уже дошли до подтверждения (`anketa.status ==
    # "pending"` — фронт решает, показывать ли иконку, по этому статусу).
    letter_required: bool | None = None
    cover_letter_text: str | None = None
    anketa: AnketaState | None = None
    # Системный перенос в «Ручной разбор» после сбоя автоотклика — короткое пояснение по-русски.
    failure_reason: str | None = None


class AutoApplySchedule(BaseModel):
    """Темп раннера — чтобы фронт показал «следующий автоотклик ≈ через N» и ETA у строк
    очереди. Всё глобальное (тик/лимит из рантайм-конфига расширения) кроме `runner_last_tick_at`
    (heartbeat конкретного аккаунта). Фронт считает ETA по позиции строки в очереди площадки."""

    runner_last_tick_at: datetime | None = None
    tick_seconds: int
    real_per_tick: int
    gap_seconds: int
    min_gap_seconds: int


class AutoApplyPreviewResponse(BaseModel):
    """Живой пересчёт очереди автооткликов одной площадки (без персиста)."""

    platform: AutoApplyPlatform
    enabled: bool
    auto: list[AutoApplyPreviewItem]
    manual_review: list[AutoApplyPreviewItem]
    applied: list[AutoApplyPreviewItem] = Field(default_factory=list)
    schedule: AutoApplySchedule
    manual_send_pending: bool = False


class AutoApplyDailyCountResponse(BaseModel):
    """Дневной лимит (2.7): сколько уже ушло сегодня и сколько осталось."""

    platform: AutoApplyPlatform
    count: int
    cap: int
    remaining: int
    # Момент последнего РЕАЛЬНОГО автоотклика площадки (серверный клок троттлинга ≤2/мин).
    # Раннер берёт max(локальная пауза, серверная) — переживает перезапуск SW / переустановку /
    # второе устройство, где модульный `realApplyClockMs` обнуляется. None = ещё не было.
    last_real_apply_at: datetime | None = None


class AutoApplyReportRequest(BaseModel):
    """Раннер сообщает об одной попытке — dry-run или реальной (2.1/2.2)."""

    platform: AutoApplyPlatform
    job_id: int
    vacancy_id: str
    dry_run: bool = True
    # Фаза 8.2: исход DOM-флоу расширения, если это не обычный успех/dry-run —
    # `captcha`/`resume_hidden`/`platform_limit`. Фаза 3.4: `needs_confirmation` — площадка в
    # режиме «Тест» (require_confirmation), раннер дошёл до финального клика, но не кликнул —
    # ждёт подтверждения владельца. Отсутствует/иное значение → обычный путь.
    outcome: str | None = None
    # Фаза 3.3: расширение распарсило анкету (outcome="anketa") — вопросы для генерации
    # ответов. Отсутствует/пусто при обычном исходе и при outcome="needs_confirmation".
    anketa_questions: list[AnketaQuestion] | None = None


class AutoApplyReportResponse(BaseModel):
    """job_id/status — только при реальной (не dry-run) успешной отправке."""

    platform: AutoApplyPlatform
    dry_run: bool
    status: str | None = None


class AutoApplyTickReport(BaseModel):
    """Итог одного тика раннера расширения — heartbeat в журнал (см. incident 2026-08-27..28:
    раннер молча не тикал 9 часов, в логах — ничего)."""

    platforms_enabled: list[str] = Field(default_factory=list)
    platforms_ready: list[str] = Field(default_factory=list)
    candidates: int = 0
    applied: int = 0
    needs_confirmation: int = 0
    anketa: int = 0
    failed: int = 0
    blocked: list[str] = Field(default_factory=list)
    # Почему раннер не смог работать: `flag_disabled` / `settings_http_502` / `preview_http_502:hh` …
    bail_reason: str | None = None


class AutoApplyPauseResponse(BaseModel):
    """Ответ kill switch (Фаза 7.4) — конфиг после того, как все площадки выключены."""

    config: AutoApplyConfig


class AutoApplyClearResponse(BaseModel):
    """Ответ ручной очистки очереди (пункт 1 редизайна «Расширения») — сколько вакансий пропущено
    по всем площадкам разом (auto + manual_review)."""

    cleared: int


class AutoApplyManualSendResponse(BaseModel):
    queued: bool = True


class AnketaPendingItem(BaseModel):
    """Одна вакансия в очереди подтверждения (Фаза 3.3 — анкета; Фаза 3.4 — простое
    подтверждение письма в режиме «Тест», `anketa.questions=[]`).

    `cover_letter_text` — денормализация `jobs.cover_letter_text` (не часть `AnketaState`,
    та же колонка, что редактируется в дровере вакансии обычным `PATCH /api/jobs/{id}`) —
    веб показывает его для правки перед подтверждением, раннер на резюме-визите (3.4) берёт
    его как готовый текст письма вместо повторной LLM-генерации.
    """

    job_id: int
    vacancy_id: str
    url: str | None = None
    title: str | None = None
    company: str | None = None
    cover_letter_text: str | None = None
    anketa: AnketaState


class AnketaPendingResponse(BaseModel):
    platform: AutoApplyPlatform
    status: str
    items: list[AnketaPendingItem] = Field(default_factory=list)


class AnketaConfirmRequest(BaseModel):
    """Владелец подтверждает анкету — возможно отредактированные ответы."""

    answers: list[AnketaAnswer]


class AutoApplyMoveRequest(BaseModel):
    """Квик-экшен «переместить» (Фаза E редизайна «Расширения», пункт 4) — ручной оверрайд
    бакета auto/manual_review, персистится отдельно от живого пересчёта (см. overrides.py)."""

    target: QueueOverride
