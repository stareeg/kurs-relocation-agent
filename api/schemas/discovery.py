"""Транспортные схемы API: конфиг и живой статус discovery (авто-открытие вакансий).

Конфиг/статус переиспользуем из ядра (`core.domains.opportunities.discovery_session`) — уже
Pydantic, без I/O, дублировать незачем (см. api/schemas/auto_apply.py — тот же приём).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.domains.opportunities.discovery_session import (
    DiscoveryConfig,
    DiscoveryEvent,
    DiscoveryPauseReason,
    DiscoveryPlatform,
    DiscoveryPlatformConfig,
    DiscoveryState,
    DiscoveryStatus,
)

__all__ = [
    "DiscoveryConfig",
    "DiscoveryEvent",
    "DiscoveryEventRemoveRequest",
    "DiscoveryPauseReason",
    "DiscoveryPlatform",
    "DiscoveryPlatformConfig",
    "DiscoverySessionAction",
    "DiscoverySessionRequest",
    "DiscoveryState",
    "DiscoveryStatus",
    "DiscoveryTickOutcome",
    "DiscoveryTickReport",
    "DiscoveryTickRequest",
]

DiscoverySessionAction = Literal["start", "pause", "resume", "stop", "clear"]
DiscoveryTickOutcome = Literal["scored", "already_known", "parse_error"]


class DiscoverySessionRequest(BaseModel):
    """Управление сессией (левая панель «Расширения»): старт/пауза/возобновление/стоп/очистка лога.

    `reason` учитывается только при `action="pause"` — расширение само решает, почему
    останавливается (пользователь нажал паузу / дневной лимит / кончились страницы / похоже
    на блокировку площадки), бэк просто переводит статус в соответствующий `paused_*`.
    `action="clear"` — кнопка «Очистить» в шапке «Просмотра»: сбрасывает только лог событий,
    сессию не останавливает.
    """

    action: DiscoverySessionAction
    reason: DiscoveryPauseReason = "user"


class DiscoveryEventRemoveRequest(BaseModel):
    """Кнопка «Удалить» на сломанной (`parse_error`) строке лога «Просмотра» — убрать одну
    вакансию, которую самопочинка не смогла долечить, не трогая остальной лог/счётчики."""

    vacancy_id: str


class DiscoveryTickRequest(BaseModel):
    """Расширение репортит исход одной открытой вакансии за тик."""

    vacancy_id: str
    outcome: DiscoveryTickOutcome
    title: str | None = None
    company: str | None = None
    # Этап 4 редизайна «Расширения» — сколько страниц листинга открыто за текущий проход
    # (discovery-runner.ts::DiscoveryCursor.pagesVisited), для подписи «страница N» в UI.
    pages_visited: int | None = None


class DiscoveryTickReport(BaseModel):
    """Итог тика раннера автопросмотра — heartbeat в журнал + `last_tick` в рантайм-стейт
    (тот же приём, что `AutoApplyTickReport`: «раннер молча не тикал» должно быть видно)."""

    platforms_running: list[str] = Field(default_factory=list)
    opened: int = 0
    scored: int = 0
    already_known: int = 0
    parse_errors: int = 0
    paused: list[str] = Field(default_factory=list)
    bail_reason: str | None = None
