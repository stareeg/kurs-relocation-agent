"""Автоотклики: конфиг по площадкам + гейт «кому автоматически, кому на ручной разбор».

Механика самой отправки (открытие вкладки, клик по «Откликнуться» на площадке) живёт в
расширении — см. README.md. Этот пакет отвечает только за решение «кого брать», не за то,
как физически кликнуть.
"""

from __future__ import annotations

from core.domains.pipeline.auto_apply.config import (
    AUTO_APPLY_DAILY_HARD_CAP,
    DEFAULT_AUTO_APPLY_CONFIG,
    KEY_AUTO_APPLY,
    AutoApplyConfig,
    AutoApplyOrder,
    AutoApplyPlatform,
    AutoApplyPlatformConfig,
    auto_apply_config_from_mapping,
    auto_apply_daily_hard_cap,
    default_auto_apply_config_dict,
    get_auto_apply_config,
    set_auto_apply_config,
)
from core.domains.pipeline.auto_apply.daily_cap import auto_apply_source, count_today
from core.domains.pipeline.auto_apply.gate import AutoApplyDecision, classify_for_auto_apply
from core.domains.pipeline.auto_apply.overrides import QueueOverride, set_override
from core.domains.pipeline.auto_apply.queue import AutoApplyQueuePreview, preview_queue
from core.domains.pipeline.auto_apply.runtime_state import (
    is_platform_limited_today,
    last_real_apply_at,
    mark_platform_limit,
)

__all__ = [
    "AUTO_APPLY_DAILY_HARD_CAP",
    "DEFAULT_AUTO_APPLY_CONFIG",
    "KEY_AUTO_APPLY",
    "AutoApplyConfig",
    "AutoApplyDecision",
    "AutoApplyOrder",
    "AutoApplyPlatform",
    "AutoApplyPlatformConfig",
    "AutoApplyQueuePreview",
    "QueueOverride",
    "auto_apply_config_from_mapping",
    "auto_apply_daily_hard_cap",
    "auto_apply_source",
    "classify_for_auto_apply",
    "count_today",
    "default_auto_apply_config_dict",
    "get_auto_apply_config",
    "is_platform_limited_today",
    "last_real_apply_at",
    "mark_platform_limit",
    "preview_queue",
    "set_auto_apply_config",
    "set_override",
]
