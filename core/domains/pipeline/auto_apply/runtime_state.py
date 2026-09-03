"""Рантайм-факты автооткликов (Фаза 8.2) — отдельно от `config.py` (это ручки владельца).

- `platform_limit` — площадка сегодня уже сигналила о СВОЁМ дневном лимите откликов (не нашем
  `daily_cap`): раннер тихо стоит для неё до завтра, не долбит один и тот же ответ каждый тик.
- `last_tick` — heartbeat раннера (jsonb-ключ `auto_apply_runner_tick`): «раннер жив / бьётся»,
  чтобы молчание в проде было видно (инцидент 2026-08-27..28). Общий механизм —
  `platform/repo/settings.record_runner_tick`.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from core.domains.pipeline.auto_apply.config import AutoApplyPlatform
from core.platform.db.pool import Executor
from core.platform.repo.settings import (
    get_runner_tick,
    get_setting,
    record_runner_tick,
    set_setting,
    should_log_runner_tick,
)

logger = logging.getLogger(__name__)

KEY_RUNTIME_STATE = "auto_apply_runtime_state"
KEY_RUNNER_TICK = "auto_apply_runner_tick"

# Сколько живёт просьба «отправить очередь сейчас», если раннер её так и не забрал.
# Полчаса — заведомо больше периода тика (`auto_apply_tick_minutes`, дефолт 5 мин) и
# заведомо меньше «через сутки внезапно посыпались боевые отклики».
MANUAL_SEND_TTL_S = 1800.0


async def mark_platform_limit(
    platform: AutoApplyPlatform, *, account_id: int, db: Executor | None = None
) -> None:
    """Запомнить: площадка сегодня уже сообщила о своём (не нашем) лимите откликов."""
    raw = await get_setting(KEY_RUNTIME_STATE, default=None, account_id=account_id, db=db)
    state: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    state[platform] = {"platform_limit_date": date.today().isoformat()}
    await set_setting(KEY_RUNTIME_STATE, state, account_id=account_id, db=db)


async def is_platform_limited_today(
    platform: AutoApplyPlatform, *, account_id: int, db: Executor | None = None
) -> bool:
    """Площадка уже сигналила о своём лимите сегодня — не пытаться снова до завтра."""
    raw = await get_setting(KEY_RUNTIME_STATE, default=None, account_id=account_id, db=db)
    if not isinstance(raw, dict):
        return False
    entry = raw.get(platform)
    if not isinstance(entry, dict):
        return False
    return entry.get("platform_limit_date") == date.today().isoformat()


async def record_real_apply(
    platform: AutoApplyPlatform, *, account_id: int, db: Executor | None = None
) -> None:
    """Запомнить момент последнего реального автоотклика площадки (наблюдаемость троттлинга
    ≤2/мин, `report_attempt`). Жёсткий потолок держит раннер (`awaitRealApplySlot`); эта метка
    нужна только чтобы засечь в журнале, если что-то его обошло."""
    try:
        raw = await get_setting(KEY_RUNTIME_STATE, default=None, account_id=account_id, db=db)
        state: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
        prev_entry = state.get(platform)
        entry: dict[str, Any] = dict(prev_entry) if isinstance(prev_entry, dict) else {}
        entry["last_real_apply"] = datetime.now(UTC).isoformat()
        state[platform] = entry
        await set_setting(KEY_RUNTIME_STATE, state, account_id=account_id, db=db)
    except Exception as exc:  # noqa: BLE001 — метка декоративна, не ломает отправку отклика
        logger.debug("record_real_apply(%s, account_id=%s): %s", platform, account_id, exc)


async def last_real_apply_at(
    platform: AutoApplyPlatform, *, account_id: int, db: Executor | None = None
) -> datetime | None:
    """Момент предыдущего реального автоотклика площадки; нет данных → None."""
    raw = await get_setting(KEY_RUNTIME_STATE, default=None, account_id=account_id, db=db)
    if not isinstance(raw, dict):
        return None
    entry = raw.get(platform)
    if not isinstance(entry, dict):
        return None
    stamp = entry.get("last_real_apply")
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


async def record_tick(
    *,
    account_id: int,
    summary: dict[str, Any] | None = None,
    logged: bool = False,
    db: Executor | None = None,
) -> None:
    await record_runner_tick(
        KEY_RUNNER_TICK, account_id=account_id, summary=summary, logged=logged, db=db
    )


async def get_last_tick(*, account_id: int, db: Executor | None = None) -> dict[str, Any] | None:
    return await get_runner_tick(KEY_RUNNER_TICK, account_id=account_id, db=db)


async def should_log_tick(*, account_id: int, db: Executor | None = None) -> bool:
    return await should_log_runner_tick(KEY_RUNNER_TICK, account_id=account_id, db=db)


async def set_manual_send_pending(
    pending: bool, *, account_id: int, db: Executor | None = None
) -> None:
    """Взвести/снять флаг «отправить очередь сейчас» (кнопка «Отправить» в «Расширении»).

    Пишем МОМЕНТ запроса, а не голый `True`: флаг снимает раннер расширения, а он может не
    прийти вообще (браузер закрыт, площадки выключены, очередь пуста) — вечно взведённый флаг
    заставлял бы раннер слать боевые отклики при первом же удобном случае через неделю после
    клика. `MANUAL_SEND_TTL_S` — срок, после которого просьба считается протухшей.
    """
    raw = await get_setting(KEY_RUNTIME_STATE, default=None, account_id=account_id, db=db)
    state: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    if pending:
        state["manual_send_pending"] = datetime.now(UTC).isoformat()
    else:
        state.pop("manual_send_pending", None)
    await set_setting(KEY_RUNTIME_STATE, state, account_id=account_id, db=db)


async def is_manual_send_pending(*, account_id: int, db: Executor | None = None) -> bool:
    """Просьба о ручной отправке ещё актуальна? Протухшая (старше `MANUAL_SEND_TTL_S`) и
    нераспознанная отметка — «нет»; легаси-`True` без времени поддержан ради записей,
    сохранённых до перехода на отметку времени."""
    raw = await get_setting(KEY_RUNTIME_STATE, default=None, account_id=account_id, db=db)
    if not isinstance(raw, dict):
        return False
    marker = raw.get("manual_send_pending")
    if marker is None or marker is False:
        return False
    if marker is True:  # легаси-формат до 2026-08-31 — считаем актуальным до явного снятия
        return True
    if not isinstance(marker, str):
        return False
    try:
        requested_at = datetime.fromisoformat(marker)
    except ValueError:
        return False
    if requested_at.tzinfo is None:
        requested_at = requested_at.replace(tzinfo=UTC)
    return (datetime.now(UTC) - requested_at).total_seconds() < MANUAL_SEND_TTL_S


__all__ = [
    "KEY_RUNNER_TICK",
    "MANUAL_SEND_TTL_S",
    "get_last_tick",
    "is_manual_send_pending",
    "is_platform_limited_today",
    "last_real_apply_at",
    "mark_platform_limit",
    "record_real_apply",
    "record_tick",
    "set_manual_send_pending",
    "should_log_tick",
]
