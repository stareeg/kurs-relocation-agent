"""Админские операции, которым нужны домены и сценарии app.

Живут здесь, а не в `core.platform.admin`: слою platform нельзя импортировать
domains/app (import-linter). HTTP по-прежнему в `api/routers/meta/admin.py`.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from core.app.scenarios import auto_apply as auto_apply_scenario
from core.domains.opportunities import discovery_session as ds
from core.domains.opportunities.discovery_session import discovery_daily_hard_cap
from core.domains.opportunities.extension_runtime_config import (
    SETTINGS_KEY,
    get_extension_runtime_config,
    reset_extension_runtime_config_cache,
    set_extension_runtime_config_override,
)
from core.domains.pipeline.auto_apply import (
    auto_apply_daily_hard_cap,
    count_today,
    get_auto_apply_config,
    preview_queue,
)
from core.domains.pipeline.auto_apply.runtime_state import get_last_tick
from core.platform.admin import service as admin_svc
from core.platform.admin.models import (
    AdminError,
    AdminPipelinePlatform,
    AdminUserPipeline,
)
from core.platform.db.pool import get_pool
from core.platform.repo.accounts import get_account_by_id

logger = logging.getLogger(__name__)

_PIPELINE_PLATFORMS: tuple[str, ...] = ("hh", "getmatch", "habr")
_EXT_CONFIG_SECTIONS = ("flags", "tuning", "apply_selectors", "parse_selectors", "text_signals")


def _extension_config_dict(cfg: Any) -> dict[str, Any]:
    return {
        "version": cfg.version,
        "origin": cfg.origin,
        "updated_at": cfg.updated_at.isoformat(),
        "flags": cfg.flags,
        "tuning": cfg.tuning,
        "apply_selectors": cfg.apply_selectors,
        "parse_selectors": cfg.parse_selectors,
        "text_signals": cfg.text_signals,
        "issues": list(cfg.issues),
    }


async def get_extension_runtime_config_admin() -> dict[str, Any]:
    """Текущий merged рантайм-конфиг расширения + плоский dump для редактирования."""
    return _extension_config_dict(await get_extension_runtime_config())


async def set_extension_runtime_config_admin(
    payload: dict[str, Any], *, actor_id: int
) -> dict[str, Any]:
    """Записать оверрайд рантайм-конфига расширения.

    Пустой оверрайд (`{}` или все секции пустые) — снять оверрайд, вернуться на репозиторный
    дефолт. Валидация мягкая на уровне домена; замечания возвращаются в `issues`.
    """
    if not isinstance(payload, dict):
        raise AdminError("Ожидается объект с секциями " + " / ".join(_EXT_CONFIG_SECTIONS))
    unknown = set(payload) - {*_EXT_CONFIG_SECTIONS, "version", "updated_at", "origin"}
    if unknown:
        raise AdminError(f"Лишние ключи: {', '.join(sorted(unknown))}")

    sections = {k: payload.get(k) or {} for k in _EXT_CONFIG_SECTIONS}
    if not any(sections.values()):
        try:
            await get_pool().execute("delete from app_settings where key = $1", SETTINGS_KEY)
        except Exception as exc:
            raise AdminError("Не удалось снять оверрайд", status=503) from exc
        reset_extension_runtime_config_cache()
        await admin_svc._log_action("extension_runtime_config", actor_id, cleared=True)
        cfg = await get_extension_runtime_config()
    else:
        cfg = await set_extension_runtime_config_override(sections)
        await admin_svc._log_action(
            "extension_runtime_config",
            actor_id,
            version=cfg.version,
            flags=sections["flags"],
            issues=len(cfg.issues),
        )
    return _extension_config_dict(cfg)


async def _extension_tick_seconds() -> int:
    cfg = await get_extension_runtime_config()
    return int(cfg.tuning.get("auto_apply_tick_minutes", 5)) * 60


async def _extension_discovery_tick_seconds() -> int:
    cfg = await get_extension_runtime_config()
    return max(1, round(float(cfg.tuning.get("discovery_tick_minutes", 1)) * 60))


async def load_user_pipeline(account_id: int) -> AdminUserPipeline:
    """Полная картина авто-процессов пользователя для вкладки «Автоматизация»."""
    row = await admin_svc._fetchrow(
        admin_svc._USER_BY_ID_SQL, account_id, name="карточка человека (пайплайн)"
    )
    if row is None:
        raise AdminError("Аккаунт не найден", status=404)

    aa_config = await get_auto_apply_config(account_id=account_id)
    d_config = await ds.get_discovery_config(account_id=account_id)
    tick_seconds = await _extension_tick_seconds()

    platforms: list[AdminPipelinePlatform] = []
    for p in _PIPELINE_PLATFORMS:
        aa = aa_config.platform(p)  # type: ignore[arg-type]
        dc = d_config.platform(p)  # type: ignore[arg-type]
        try:
            dstatus = await ds.get_discovery_status(p, account_id=account_id)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — статус декоративен
            logger.debug("admin pipeline: discovery status %s/%s: %s", account_id, p, exc)
            dstatus = ds.DiscoveryStatus(platform=p)  # type: ignore[arg-type]
        preview = await preview_queue(p, account_id=account_id)  # type: ignore[arg-type]
        pending = sum(
            1
            for j in (*preview.auto, *preview.manual_review)
            if j.anketa and j.anketa.get("status") == "pending"
        )
        platforms.append(
            AdminPipelinePlatform(
                platform=p,
                discovery_state=dstatus.state,
                discovery_daily_cap=discovery_daily_hard_cap(p),
                discovery_used_today=dstatus.daily_used,
                discovery_opened_session=dstatus.opened,
                discovery_search_urls=len([u for u in dc.search_urls if u.strip()]),
                auto_apply_enabled=aa.enabled,
                auto_apply_daily_cap=auto_apply_daily_hard_cap(p),  # type: ignore[arg-type]
                auto_apply_min_score=aa.min_score,
                auto_apply_manual_band=aa.manual_review_band,
                auto_apply_dry_run=aa.dry_run or aa.require_confirmation,
                queue_auto=len(preview.auto),
                queue_manual=len(preview.manual_review),
                pending_confirm=pending,
                applied_today=await count_today(p, account_id=account_id),  # type: ignore[arg-type]
            )
        )

    aa_tick = await get_last_tick(account_id=account_id)
    d_tick = await ds.get_last_runner_tick(account_id=account_id)
    aa_tick_at = admin_svc._runner_tick_at(aa_tick)
    disc_tick_seconds = await _extension_discovery_tick_seconds()
    return AdminUserPipeline(
        platforms=platforms,
        discovery_last_tick_at=admin_svc._runner_tick_at(d_tick),
        auto_apply_last_tick_at=aa_tick_at,
        auto_apply_next_tick_eta=(
            aa_tick_at + timedelta(seconds=tick_seconds) if aa_tick_at else None
        ),
        tick_seconds=tick_seconds,
        discovery_tick_seconds=disc_tick_seconds,
        any_discovery_running=any(pl.discovery_state == "running" for pl in platforms),
        any_auto_apply_enabled=any(pl.auto_apply_enabled for pl in platforms),
    )


async def pause_user_auto_apply(account_id: int, *, actor_id: int) -> None:
    """Оператор гасит автоотклики пользователя."""
    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    await auto_apply_scenario.pause_all(account_id=account_id)
    await admin_svc._log_action("auto_apply_pause", actor_id, target_account_id=account_id)


async def resume_user_auto_apply(account_id: int, *, actor_id: int) -> None:
    """Оператор возобновляет автоотклики пользователя."""
    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    await auto_apply_scenario.resume_all(account_id=account_id)
    await admin_svc._log_action("auto_apply_resume", actor_id, target_account_id=account_id)


async def clear_user_auto_apply_queue(account_id: int, *, actor_id: int) -> int:
    """Оператор чистит очередь автооткликов пользователя."""
    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    cleared = await auto_apply_scenario.clear_queue(account_id=account_id)
    await admin_svc._log_action(
        "auto_apply_clear", actor_id, target_account_id=account_id, cleared=cleared
    )
    return cleared


async def stop_user_discovery(account_id: int, *, platform: str | None, actor_id: int) -> list[str]:
    """Оператор останавливает автопросмотр — одну площадку или все три."""
    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    targets = [platform] if platform in _PIPELINE_PLATFORMS else list(_PIPELINE_PLATFORMS)
    stopped: list[str] = []
    for p in targets:
        try:
            status = await ds.get_discovery_status(p, account_id=account_id)  # type: ignore[arg-type]
            if status.state == "idle":
                continue
            await ds.stop_session(p, account_id=account_id)  # type: ignore[arg-type]
            stopped.append(p)
        except Exception as exc:  # noqa: BLE001 — одна площадка не роняет остальные
            logger.warning("admin: стоп автопросмотра %s/%s не удался: %s", account_id, p, exc)
    await admin_svc._log_action(
        "discovery_stop", actor_id, target_account_id=account_id, platforms=stopped
    )
    return stopped


async def clear_user_discovery_log(account_id: int, *, actor_id: int) -> None:
    """Оператор чистит лог автопросмотра по всем площадкам."""
    if await get_account_by_id(account_id) is None:
        raise AdminError("Аккаунт не найден", status=404)
    for p in _PIPELINE_PLATFORMS:
        try:
            await ds.clear_events(p, account_id=account_id)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001
            logger.warning("admin: очистка лога автопросмотра %s/%s: %s", account_id, p, exc)
    await admin_svc._log_action("discovery_clear_log", actor_id, target_account_id=account_id)


__all__ = [
    "clear_user_auto_apply_queue",
    "clear_user_discovery_log",
    "get_extension_runtime_config_admin",
    "load_user_pipeline",
    "pause_user_auto_apply",
    "resume_user_auto_apply",
    "set_extension_runtime_config_admin",
    "stop_user_discovery",
]
