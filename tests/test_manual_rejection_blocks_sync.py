"""Регресс инцидента «Толк» (vacancy 89, 2026-08): владелец увёл вакансию в «Отказ» через
drag-and-drop на канбане, но тихий heartbeat-синк откликов (`hh_negotiations`) каждые ~15 минут
возвращал её в «Скрининг» — `should_apply_funnel_update` считал «Приглашение» на hh.ru фактом
возобновления процесса.

Правило после фикса: если текущий статус «Отказ» и его источник в `application_stages` —
осознанное решение владельца (`api_kanban`/`telegram_bot`/`vacancy_page`/`api_funnel`/
`chat_archive`/`debrief_auto_reject`), авто-синк площадки НЕ воскрешает вакансию в активную
воронку. Вернуть её может только сам владелец вручную или HR в «Чатах» (отдельный код-путь).
"""

from __future__ import annotations

from typing import Any

import pytest

from core.config import get_settings
from core.domains.offers.hh_negotiations import (
    HhNegotiationStatus,
    NegotiationSyncItem,
    should_apply_funnel_update,
)
from core.domains.opportunities.jobs import Job, is_manual_rejection_source
from core.domains.pipeline import negotiations
from core.kernel.schemas.funnel import FunnelStatus

# --- Чистый guard ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("proposed", "expected"),
    [
        (FunnelStatus.SCREENING.value, False),  # «Приглашение» → воскрешение запрещено
        (FunnelStatus.APPLIED.value, False),
        (FunnelStatus.TECH.value, False),
        (FunnelStatus.REJECTED.value, True),  # повторный «Отказ» — не воскрешение
    ],
)
def test_manual_rejection_blocks_auto_revival(proposed: str, expected: bool) -> None:
    result = should_apply_funnel_update(
        FunnelStatus.REJECTED.value,
        proposed,
        hh_status=HhNegotiationStatus.UNKNOWN,
        force=False,
        current_is_manual_rejection=True,
    )
    assert result is expected


def test_auto_rejection_still_can_be_revived() -> None:
    """Авто-«Отказ» (stale_ttl/hh_negotiations) — обычное поведение «возобновление после листа
    Отказы» остаётся: без ручного отказа синк вправе вернуть вакансию в воронку."""
    assert (
        should_apply_funnel_update(
            FunnelStatus.REJECTED.value,
            FunnelStatus.SCREENING.value,
            hh_status=HhNegotiationStatus.UNKNOWN,
            force=False,
            current_is_manual_rejection=False,
        )
        is True
    )


def test_manual_rejection_source_classification() -> None:
    assert is_manual_rejection_source("api_kanban") is True
    assert is_manual_rejection_source("telegram_bot") is True
    assert is_manual_rejection_source("chat_archive") is True
    assert is_manual_rejection_source("debrief_auto_reject") is True
    assert is_manual_rejection_source("hh_negotiations") is False
    assert is_manual_rejection_source("stale_ttl") is False
    assert is_manual_rejection_source("getmatch") is False
    assert is_manual_rejection_source(None) is False


# --- _sync_one: ручной отказ не воскрешается -------------------------------------


def _sync_job(status: str, *, job_id: int = 89, vacancy_id: str = "123456") -> Job:
    return Job(id=job_id, vacancy_id=vacancy_id, vacancy_text="", status=status)


def _item(vacancy_id: str = "123456") -> NegotiationSyncItem:
    return NegotiationSyncItem(
        vacancy_id=vacancy_id,
        hh_status_raw="Приглашение на собеседование",
        company="Толк",
        title="ML-разработчик middle+",
    )


@pytest.mark.asyncio
async def test_sync_one_does_not_revive_manually_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Владелец драгнул карточку в «Отказ» (source=api_kanban) → HH присылает «Приглашение».
    `_sync_one` обязан оставить «Отказ» (applied=False, skipped=True), а не вернуть в «Скрининг»."""

    async def fake_latest_rejection_source(job_id: int, *, account_id: int, db=None) -> str:
        return "api_kanban"

    monkeypatch.setattr(negotiations, "latest_rejection_source", fake_latest_rejection_source)

    result = await negotiations._sync_one(
        _item(),
        dry_run=True,
        use_llm=False,
        force=False,
        settings=get_settings(),
        job=_sync_job(FunnelStatus.REJECTED.value),
        account_id=1,
    )

    assert result.applied is False
    assert result.skipped is True
    assert "Отказ" in result.reason


@pytest.mark.asyncio
async def test_sync_one_revives_auto_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Авто-«Отказ» (stale_ttl) → HH присылает «Приглашение»: синк вправе вернуть в воронку."""

    async def fake_latest_rejection_source(job_id: int, *, account_id: int, db=None) -> str:
        return "stale_ttl"

    monkeypatch.setattr(negotiations, "latest_rejection_source", fake_latest_rejection_source)

    result = await negotiations._sync_one(
        _item(),
        dry_run=True,
        use_llm=False,
        force=False,
        settings=get_settings(),
        job=_sync_job(FunnelStatus.REJECTED.value),
        account_id=1,
    )

    assert result.applied is True
    assert result.skipped is False


@pytest.mark.asyncio
async def test_sync_one_does_not_ask_llm_for_manual_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При ручном «Отказе» LLM-guard-override (EX-8) не должен вызываться вовсе: решение владельца
    не отдаётся на усмотрение модели с куцым бейджем hh.ru."""

    async def fake_latest_rejection_source(job_id: int, *, account_id: int, db=None) -> str:
        return "api_kanban"

    monkeypatch.setattr(negotiations, "latest_rejection_source", fake_latest_rejection_source)

    called: list[bool] = []

    async def fake_llm(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
        called.append(True)
        return FunnelStatus.SCREENING.value, "выдуманный разбор"

    monkeypatch.setattr(negotiations, "resolve_funnel_status_llm", fake_llm, raising=False)

    result = await negotiations._sync_one(
        _item(),
        dry_run=True,
        use_llm=True,
        force=False,
        settings=get_settings(),
        job=_sync_job(FunnelStatus.REJECTED.value),
        account_id=1,
    )

    assert result.applied is False
    assert not called, "LLM-guard-override не должен вызываться при ручном отказе"
