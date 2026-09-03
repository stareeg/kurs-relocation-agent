"""Фасад настроек ядра: реализация в `core.platform.config`.

Импорты `from core.config import get_settings, CoreSettings, …` остаются каноном для
доменов и api. Секции: DbSettings / LlmSettings / AppSettings / IntegrationSettings.
"""

from __future__ import annotations

from core.platform.config import (
    AppSettings,
    ConfigError,
    CoreSettings,
    DbSettings,
    IntegrationSettings,
    LlmSettings,
    account_openrouter_key_cache_stale,
    cache_account_openrouter_key,
    clear_settings_cache,
    current_account_id,
    current_account_openrouter_key,
    ensure_env_file,
    get_settings,
    load_settings,
    normalize_openrouter_model,
    reset_current_account_id,
    runtime_openrouter_key,
    set_current_account_id,
    set_runtime_openrouter_key,
    strip_blank_numeric_env,
)

__all__ = [
    "AppSettings",
    "ConfigError",
    "CoreSettings",
    "DbSettings",
    "IntegrationSettings",
    "LlmSettings",
    "account_openrouter_key_cache_stale",
    "cache_account_openrouter_key",
    "clear_settings_cache",
    "current_account_id",
    "current_account_openrouter_key",
    "ensure_env_file",
    "get_settings",
    "load_settings",
    "normalize_openrouter_model",
    "reset_current_account_id",
    "runtime_openrouter_key",
    "set_current_account_id",
    "set_runtime_openrouter_key",
    "strip_blank_numeric_env",
]
